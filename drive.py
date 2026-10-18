"""One PowerFlex 525 drive.

A ``Drive`` can be used two ways:

* ad hoc: every call opens (and closes) its own EtherNet/IP session, or
* as a context manager: ``with Drive(ip) as d:`` opens ONE session that every
  call inside the block reuses. Bulk operations should always do this.

Writes are guarded: they read the current values first, skip values that already
match, refuse parameters that cannot be written while the drive runs, save the
old values to a backup file, and read back to verify.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pycomm3

from . import constants as C
from .errors import (CommError, ConfigError, DeviceStateConflict, DriveBusyError, PF525Error,
                     WriteVerifyError)
from .labels import label
from .parameter import ParameterInfo, online_read_full_type

# WriteResult.status values
WRITTEN = "written"
UNCHANGED = "unchanged"
DRY_RUN = "dry_run"
BLOCKED_RUNNING = "blocked_running"
NOT_WRITABLE = "not_writable"
VERIFY_FAILED = "verify_failed"
OK_STATUSES = (WRITTEN, UNCHANGED)


def to_signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _check_parameter(parameter) -> int:
    p = int(parameter)
    if not 1 <= p <= 0xFFFF:
        raise ValueError(f"Parameter number out of range: {parameter!r}")
    return p


def _check_value(value) -> int:
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"Parameter values must be whole numbers, got {value!r}")
        value = int(value)
    value = int(value)
    if not -0x8000 <= value <= 0xFFFF:
        raise ValueError(f"Value {value} does not fit in 16 bits")
    return value


def normalize_items(items: Mapping[int, int] | Iterable[tuple[int, int]]) -> dict[int, int]:
    """Validate ``{param: value}`` or ``[(param, value), ...]``; later duplicates win."""
    pairs = items.items() if isinstance(items, Mapping) else items
    out: dict[int, int] = {}
    for parameter, value in pairs:
        out[_check_parameter(parameter)] = _check_value(value)
    return out


@dataclass
class WriteResult:
    parameter: int
    old: int | None
    new: int
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in OK_STATUSES or self.status == DRY_RUN

    @property
    def name(self) -> str:
        return label(self.parameter)

    def __str__(self) -> str:
        text = f"P{self.parameter:03d} {self.name}: {self.old} -> {self.new} [{self.status}]"
        return f"{text} {self.detail}" if self.detail else text


@dataclass
class AutotuneResult:
    success: bool
    reason: str = ""
    rr_before: int | None = None
    rr_after: int | None = None
    cleanup_errors: list[str] = field(default_factory=list)


class Drive:
    def __init__(self, ip: str, log: logging.Logger | None = None):
        self.ip = str(ipaddress.ip_address(ip))
        self.log = log or logging.getLogger(f"pf525.drive.{self.ip}")
        self._lock = threading.RLock()
        self._stack: ExitStack | None = None
        self._cip = None
        self._depth = 0

    def __repr__(self):
        return f"Drive({self.ip!r})"

    __str__ = __repr__

    # ------------------------------------------------------------------ session
    def __enter__(self):
        with self._lock:
            if self._depth == 0:
                stack = ExitStack()
                try:
                    self._cip = stack.enter_context(pycomm3.CIPDriver(self.ip))
                except pycomm3.CommError as exc:
                    raise CommError(f"Drive {self.ip} could not be reached: {exc}") from exc
                self._stack = stack
            self._depth += 1
        return self

    def __exit__(self, *exc_info):
        with self._lock:
            self._depth -= 1
            if self._depth == 0 and self._stack is not None:
                try:
                    self._stack.close()
                finally:
                    self._stack = None
                    self._cip = None
        return False

    @contextmanager
    def _io(self):
        with self._lock:
            try:
                if self._cip is not None:
                    yield self._cip
                else:
                    with pycomm3.CIPDriver(self.ip) as cip:
                        yield cip
            except pycomm3.CommError as exc:
                raise CommError(f"Drive {self.ip} could not be reached: {exc}") from exc

    def _message(self, **kwargs):
        with self._io() as cip:
            result = cip.generic_message(connected=False, route_path=False, **kwargs)
        error = getattr(result, "error", None)
        if error:
            if "Device state conflict" in str(error):
                raise DeviceStateConflict()
            raise PF525Error(f"Drive {self.ip} returned an error: {error}")
        return result

    # -------------------------------------------------------------------- reads
    def read_parameter(self, parameter: int, signed: bool = False) -> int:
        """Read one parameter as a raw unsigned 16-bit value (``signed=True`` for two's complement)."""
        p = _check_parameter(parameter)
        result = self._message(service=pycomm3.Services.get_attribute_single,
                               class_code=C.PARAM_CLASS, instance=p,
                               attribute=C.ATTR_PARAM_VALUE, data_type=pycomm3.UINT)
        if result.value is None:
            raise PF525Error(f"Drive {self.ip} returned no value for parameter {p}")
        self.log.debug("Read P%s = %s from %s", p, result.value, self.ip)
        return to_signed16(result.value) if signed else result.value

    def parameter_count(self) -> int:
        result = self._message(service=pycomm3.Services.get_attribute_single,
                               class_code=C.PARAM_CLASS, instance=0,
                               attribute=C.ATTR_PARAM_COUNT, data_type=pycomm3.UINT)
        if result.value is None:
            raise PF525Error(f"Drive {self.ip} did not report its parameter count")
        return result.value

    def read_logic_command(self) -> int:
        result = self._message(service=pycomm3.Services.get_attribute_single,
                               class_code=pycomm3.ClassCode.register,
                               instance=C.LOGIC_COMMAND_INSTANCE,
                               attribute=C.LOGIC_COMMAND_ATTR, data_type=pycomm3.UINT)
        return result.value

    @staticmethod
    def _param_item():
        return pycomm3.Struct(pycomm3.UINT("parameter"), pycomm3.UINT("value"))

    def _scattered_read_chunk(self, parameters: list[int]) -> list[int]:
        item = self._param_item()
        pairs = [(p, 0) for p in parameters]
        result = self._message(service=C.SVC_SCATTERED_READ, class_code=C.PARAM_CLASS, instance=0,
                               request_data=item[len(pairs)].encode(pairs),
                               data_type=item[len(pairs)])
        values = [row["value"] for row in result.value]
        if len(values) != len(parameters):
            raise PF525Error(f"Drive {self.ip} returned {len(values)} values for "
                             f"{len(parameters)} parameters")
        return values

    def read_parameters(self, parameters: Iterable[int], signed: Iterable[int] = ()) -> dict[int, int]:
        """Read many parameters (64 per request). Returns ``{parameter: value}``."""
        wanted = list(dict.fromkeys(_check_parameter(p) for p in parameters))
        signed = set(signed)
        values: dict[int, int] = {}
        for start in range(0, len(wanted), C.SCATTER_CHUNK):
            chunk = wanted[start:start + C.SCATTER_CHUNK]
            values.update(zip(chunk, self._scattered_read_chunk(chunk)))
        for p in signed & values.keys():
            values[p] = to_signed16(values[p])
        return values

    def read_all(self) -> dict[int, int]:
        """Every parameter the drive reports, as ``{parameter: value}``."""
        with self:
            count = self.parameter_count()
            values = self.read_parameters(range(1, count + 1))
        self.log.info("Read all %s parameters from %s", count, self.ip)
        return values

    def read_parameter_info(self, parameter: int) -> ParameterInfo:
        """Descriptor, limits, scaling and name for one parameter."""
        p = _check_parameter(parameter)
        result = self._message(service=pycomm3.Services.get_attribute_single,
                               class_code=C.PARAM_CLASS, instance=p,
                               attribute=C.ATTR_ONLINE_READ_FULL,
                               data_type=online_read_full_type()[1])
        return ParameterInfo(p, dict(result.value[0]))

    def read_all_parameter_info(self) -> dict[int, ParameterInfo]:
        with self:
            count = self.parameter_count()
            return {p: self.read_parameter_info(p) for p in range(1, count + 1)}

    def is_running(self) -> bool:
        return bool(self.read_parameter(C.P_DRIVE_STATUS) & C.RUNNING_STATUS_MASK)

    # ------------------------------------------------------------------- writes
    def _write_logic_command(self, value: int):
        self._message(service=pycomm3.Services.set_attribute_single,
                      class_code=pycomm3.ClassCode.register, instance=C.LOGIC_COMMAND_INSTANCE,
                      attribute=C.LOGIC_COMMAND_ATTR, request_data=pycomm3.UINT.encode(value))

    def _write_logic_timeout(self, seconds: int):
        self._message(service=pycomm3.Services.set_attribute_single,
                      class_code=pycomm3.ClassCode.register, instance=C.LOGIC_TIMEOUT_INSTANCE,
                      attribute=C.LOGIC_TIMEOUT_ATTR, request_data=pycomm3.UINT.encode(seconds))

    def _write_chunk(self, items: dict[int, int]):
        if len(items) == 1:
            ((p, v),) = items.items()
            self._message(service=pycomm3.Services.set_attribute_single,
                          class_code=C.PARAM_CLASS, instance=p, attribute=C.ATTR_PARAM_VALUE,
                          request_data=pycomm3.UINT.encode(v & 0xFFFF))
            return
        item = self._param_item()
        pairs = [(p, v & 0xFFFF) for p, v in items.items()]
        self._message(service=C.SVC_SCATTERED_WRITE, class_code=C.PARAM_CLASS, instance=0,
                      request_data=item[len(pairs)].encode(pairs), data_type=item[len(pairs)])

    def write_backup(self, values: Mapping[int, int], directory=C.DEFAULT_BACKUP_DIR,
                     reason: str = "") -> Path:
        """Save ``{parameter: value}`` to a timestamped JSON file and return its path."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"{self.ip}_{stamp}.json"
        counter = 1
        while path.exists():
            path = directory / f"{self.ip}_{stamp}_{counter}.json"
            counter += 1
        payload = {"ip": self.ip, "created": datetime.now().isoformat(timespec="seconds"),
                   "reason": reason, "values": {str(p): v for p, v in values.items()}}
        path.write_text(json.dumps(payload, indent=2))
        self.log.info("Backup of %s parameters from %s saved to %s", len(values), self.ip, path)
        return path

    def backup(self, directory=C.DEFAULT_BACKUP_DIR, parameters: Iterable[int] | None = None) -> Path:
        """Snapshot some (default: all) parameters to a JSON file."""
        with self:
            values = (self.read_parameters(parameters) if parameters is not None
                      else self.read_all())
        return self.write_backup(values, directory, reason="manual backup")

    def write_parameters(self, items, *, dry_run: bool = False, verify: bool = True,
                         require_stopped: bool = True, skip_unchanged: bool = True,
                         backup_dir=C.DEFAULT_BACKUP_DIR) -> list[WriteResult]:
        """Write ``{parameter: value}`` safely and report what happened to each one.

        * values equal to the drive's current value are skipped,
        * if the drive is running, parameters that are read-only or not writable
          while enabled are refused (``blocked_running`` / ``not_writable``),
        * the old values of everything about to change are saved to ``backup_dir``
          (``None`` disables the backup),
        * ``dry_run=True`` changes nothing and reports what would happen,
        * ``verify=True`` reads every written value back.
        """
        wanted = normalize_items(items)
        if not wanted:
            return []
        with self:
            current = self.read_parameters(wanted)
            results: dict[int, WriteResult] = {}
            todo: dict[int, int] = {}
            for p, new in wanted.items():
                old = current[p]
                if skip_unchanged and (old & 0xFFFF) == (new & 0xFFFF):
                    results[p] = WriteResult(p, old, new, UNCHANGED)
                else:
                    todo[p] = new

            if todo and require_stopped and self.is_running():
                for p in list(todo):
                    info = self.read_parameter_info(p)
                    if not info.writable:
                        results[p] = WriteResult(p, current[p], todo.pop(p), NOT_WRITABLE,
                                                 "parameter is read only or does not exist")
                    elif not info.writable_when_running:
                        results[p] = WriteResult(p, current[p], todo.pop(p), BLOCKED_RUNNING,
                                                 "cannot be written while the drive is running")

            if dry_run:
                for p, new in todo.items():
                    results[p] = WriteResult(p, current[p], new, DRY_RUN)
            elif todo:
                if backup_dir is not None:
                    self.write_backup({p: current[p] for p in todo}, backup_dir,
                                      reason="before write")
                names = list(todo)
                for start in range(0, len(names), C.SCATTER_CHUNK):
                    chunk = {p: todo[p] for p in names[start:start + C.SCATTER_CHUNK]}
                    self._write_chunk(chunk)
                    after = self.read_parameters(chunk) if verify else {}
                    for p, new in chunk.items():
                        if verify and (after[p] & 0xFFFF) != (new & 0xFFFF):
                            results[p] = WriteResult(p, current[p], new, VERIFY_FAILED,
                                                     f"read back {after[p]}")
                            self.log.error("P%s write to %s failed verification (wrote %s, read %s)",
                                           p, self.ip, new, after[p])
                        else:
                            results[p] = WriteResult(p, current[p], new, WRITTEN)
                            self.log.info("Wrote P%s = %s to %s", p, new, self.ip)
        return [results[p] for p in wanted]

    def write_parameter(self, parameter: int, value: int, *, dry_run: bool = False,
                        verify: bool = True, require_stopped: bool = True,
                        backup_dir=C.DEFAULT_BACKUP_DIR) -> WriteResult:
        """Write one parameter; raises if it was refused or failed verification."""
        (result,) = self.write_parameters({parameter: value}, dry_run=dry_run, verify=verify,
                                          require_stopped=require_stopped, backup_dir=backup_dir)
        if result.status == VERIFY_FAILED:
            raise WriteVerifyError(f"{self.ip}: {result}")
        if result.status == BLOCKED_RUNNING:
            raise DriveBusyError(f"{self.ip}: {result}")
        if result.status == NOT_WRITABLE:
            raise PF525Error(f"{self.ip}: {result}")
        return result

    def restore(self, path, *, dry_run: bool = False, allow_other_drive: bool = False,
                backup_dir=C.DEFAULT_BACKUP_DIR) -> list[WriteResult]:
        """Write the values saved in a backup file back to the drive."""
        data = json.loads(Path(path).read_text())
        if data.get("ip") != self.ip and not allow_other_drive:
            raise ConfigError(f"Backup {path} is for drive {data.get('ip')}, not {self.ip}")
        values = {int(p): v for p, v in data["values"].items()}
        return self.write_parameters(values, dry_run=dry_run, backup_dir=backup_dir)

    # ----------------------------------------------------------------- autotune
    def autotune(self, timeout: int = 60, poll_interval: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep) -> AutotuneResult:
        """Run a static autotune and report whether Motor Rr (P498) was measured.

        Motor Rr is cleared to detect completion. If the tune does not finish, the
        old Rr, start source and speed reference are written back so the drive is
        not left in a worse state. The drive must be stopped.
        """
        with self:
            if self.is_running():
                raise DriveBusyError(f"Drive {self.ip} is running; stop it before autotuning")
            saved46 = self.read_parameter(C.P_START_SOURCE)
            saved47 = self.read_parameter(C.P_SPEED_REFERENCE)
            rr_before = self.read_parameter(C.P_MOTOR_RR)
            result = AutotuneResult(False, rr_before=rr_before, rr_after=rr_before)

            def best_effort(what, fn, *args):
                try:
                    fn(*args)
                except Exception as exc:  # cleanup must never mask the original error
                    self.log.error("Autotune cleanup step '%s' failed on %s: %s", what, self.ip, exc)
                    result.cleanup_errors.append(f"{what}: {exc}")

            def put(parameter, value):
                self.write_parameter(parameter, value, require_stopped=False, backup_dir=None)

            # If the host dies mid-tune the drive faults after `timeout` seconds.
            self._write_logic_timeout(timeout)
            try:
                put(C.P_START_SOURCE, 5)
                put(C.P_SPEED_REFERENCE, 15)
                if self.read_logic_command() != C.LOGIC_STOP:
                    self._write_logic_command(C.LOGIC_CLEAR_FAULTS)
                self._write_logic_command(C.LOGIC_RELEASE)
                put(C.P_AUTOTUNE, 1)                     # static tune
                put(C.P_MOTOR_RR, 0)                     # polled to detect completion
                self._write_logic_command(C.LOGIC_START)
                waited = 0.0
                while waited < timeout:
                    sleep(poll_interval)
                    waited += poll_interval
                    rr = self.read_parameter(C.P_MOTOR_RR)
                    if rr != 0:
                        result.success, result.rr_after = True, rr
                        break
                else:
                    result.reason = f"Timed out after {timeout}s waiting for Motor Rr (P498)"
            except DeviceStateConflict as exc:
                result.reason = str(exc)
            finally:
                best_effort("stop command", self._write_logic_command, C.LOGIC_STOP)
                best_effort("disable comm timeout", self._write_logic_timeout, 0)
                best_effort("restore P46", put, C.P_START_SOURCE, saved46)
                best_effort("restore P47", put, C.P_SPEED_REFERENCE, saved47)
                if not result.success and rr_before != 0:
                    best_effort("restore P498", put, C.P_MOTOR_RR, rr_before)
            if result.success:
                self.log.info("Autotune of %s finished: Motor Rr = %s", self.ip, result.rr_after)
            else:
                self.log.error("Autotune of %s failed: %s", self.ip, result.reason)
            return result

    # ------------------------------------------- names used by the original scripts
    def read_pf525_parameter(self, parameter):
        return self.read_parameter(parameter)

    def write_pf525_parameter(self, parameter, value, Check=True):
        return self.write_parameter(parameter, value, verify=Check)

    def read_pf525_logic_command(self):
        return self.read_logic_command()

    def read_all_pf525_data(self):
        return {"drive": self.ip, "data": self.read_all()}

    def detailed_read_all_pf525_data(self):
        return [info.as_dict() for info in self.read_all_parameter_info().values()]

    def drive_autotune(self):
        return self.autotune()

    def scattered_read(self, read_list):
        values = self.read_parameters(read_list)
        return [values[int(p)] for p in read_list]

    def scattered_write(self, write_params):
        return self.write_parameters(write_params)
