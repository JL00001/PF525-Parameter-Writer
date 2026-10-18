"""A collection of drives and the bulk operations that run across them.

Per-drive work runs in a thread pool (it is all network I/O), and each drive does
its work inside one reused EtherNet/IP session. One drive failing never aborts the
others: errors are collected per IP in a ``BatchResult``.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import pycomm3

from . import constants as C
from .drive import DRY_RUN, OK_STATUSES, Drive, WriteResult, _check_parameter, _check_value
from .errors import ConfigError, ConfirmationRequired, PF525Error
from .health import (REQUIRED_READS, Finding, HealthConfig, HealthReport, drive_is_running,
                     evaluate)
from .labels import label

POWERFLEX_525 = "PowerFlex 525"


@dataclass
class BatchResult:
    """Per-drive results of a bulk operation."""

    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def format_errors(self) -> str:
        return "\n".join(f"{ip}: {exc}" for ip, exc in sorted(self.errors.items()))


@dataclass
class DumpResult:
    path: Path
    errors: dict[str, Exception]


def read_parameter_sheet(filename) -> dict[str, dict[int, int]]:
    """Parse a parameter spreadsheet into ``{ip: {parameter: value}}``.

    Layout (same as the dump and the template): column A = parameter number,
    column B = name, row 1 = drive IP addresses; empty cells are ignored.
    """
    try:
        frame = pd.read_excel(filename, header=0, index_col=0)
    except PermissionError as exc:
        raise ConfigError(f"{filename} is open in another program; close it and try again") from exc
    except FileNotFoundError as exc:
        raise ConfigError(f"{filename} does not exist") from exc

    changes: dict[str, dict[int, int]] = {}
    for column in frame.columns:
        header = str(column).strip()
        if header == "Name" or header.startswith("Unnamed"):
            continue
        try:
            ip = str(ipaddress.ip_address(header))
        except ValueError as exc:
            raise ConfigError(f"Column header {header!r} in {filename} is not an IP address") from exc
        if ip in changes:
            raise ConfigError(f"{ip} appears in more than one column of {filename}")
        wanted: dict[int, int] = {}
        for parameter, value in frame[column].items():
            if pd.isna(value):
                continue
            try:
                wanted[_check_parameter(parameter)] = _check_value(value)
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"{filename}: drive {ip}, parameter {parameter!r}: {exc}") from exc
        if wanted:
            changes[ip] = wanted
    return changes


def _fix_status(statuses: Iterable[str], dry_run: bool) -> str:
    for status in statuses:
        if status not in (*OK_STATUSES, DRY_RUN):
            return status
    return "planned" if dry_run else "fixed"


class Network:
    def __init__(self, log: logging.Logger | None = None, max_workers: int = 16,
                 backup_dir=C.DEFAULT_BACKUP_DIR, discover_seconds: float | None = None):
        self.log = log or logging.getLogger("pf525.network")
        self.max_workers = max(1, max_workers)
        self.backup_dir = backup_dir
        self.drives: dict[str, Drive] = {}
        if discover_seconds:
            self.discover(discover_seconds)

    # ------------------------------------------------------------ drive list
    def add_drive(self, ip: str) -> Drive:
        drive = Drive(ip, self.log)
        return self.drives.setdefault(drive.ip, drive)

    def discover(self, duration: float = 10.0, interval: float = 1.0) -> list[str]:
        """Broadcast for PowerFlex 525 drives for ``duration`` seconds; returns new IPs."""
        found: list[str] = []
        deadline = time.monotonic() + duration
        while True:
            for node in pycomm3.CIPDriver.discover():
                if "ip_address" not in node:
                    continue
                if not str(node.get("product_name", "")).startswith(POWERFLEX_525):
                    continue
                ip = node["ip_address"]
                if ip not in self.drives:
                    self.add_drive(ip)
                    found.append(ip)
                    self.log.info("Discovered PowerFlex 525 at %s", ip)
            if time.monotonic() >= deadline:
                return found
            time.sleep(interval)

    def _drive(self, ip: str) -> Drive:
        try:
            return self.drives[str(ipaddress.ip_address(ip))]
        except (KeyError, ValueError):
            raise PF525Error(f"{ip} is not in the drive list") from None

    def _targets(self, ips: Iterable[str] | None) -> list[str]:
        if ips is None:
            return sorted(self.drives, key=ipaddress.ip_address)
        return [self._drive(ip).ip for ip in ips]

    # ------------------------------------------------------------ the engine
    def _run(self, fn: Callable[[Drive], Any], ips: Iterable[str] | None = None) -> BatchResult:
        targets = self._targets(ips)
        batch = BatchResult()
        if not targets:
            return batch

        def job(drive: Drive):
            with drive:                      # one session for everything this job does
                return fn(drive)

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(targets))) as pool:
            futures = {ip: pool.submit(job, self.drives[ip]) for ip in targets}
        for ip, future in futures.items():
            try:
                batch.values[ip] = future.result()
            except Exception as exc:         # per-drive failure; reported, not fatal
                batch.errors[ip] = exc
                self.log.error("%s: %s", ip, exc)
        return batch

    # --------------------------------------------------------- single drive
    def read_parameter(self, ip: str, parameter: int) -> int:
        return self._drive(ip).read_parameter(parameter)

    def write_parameter(self, ip: str, parameter: int, value: int, dry_run: bool = False) -> WriteResult:
        return self._drive(ip).write_parameter(parameter, value, dry_run=dry_run,
                                               backup_dir=self.backup_dir)

    # ----------------------------------------------------------- all drives
    def read(self, parameter: int, ips: Iterable[str] | None = None) -> BatchResult:
        """Read one parameter from every drive."""
        return self._run(lambda d: d.read_parameter(parameter), ips)

    def write(self, parameter: int, value: int, dry_run: bool = False,
              ips: Iterable[str] | None = None) -> BatchResult:
        """Write one parameter on every drive (guarded: see ``Drive.write_parameters``)."""
        return self._run(lambda d: d.write_parameter(parameter, value, dry_run=dry_run,
                                                     backup_dir=self.backup_dir), ips)

    def search(self, parameter: int, value: int, match: bool = False,
               ips: Iterable[str] | None = None) -> BatchResult:
        """Drives whose parameter differs from ``value`` (or equals it with ``match=True``)."""
        batch = self.read(parameter, ips)
        batch.values = {ip: v for ip, v in batch.values.items() if (v == value) == match}
        return batch

    # ------------------------------------------------------------ spreadsheets
    def dump(self, file="Drive Parameter Dump", ips: Iterable[str] | None = None) -> DumpResult:
        """Read every parameter of every drive into an Excel file (parameters down, drives across)."""
        batch = self._run(lambda d: d.read_all(), ips)
        if not batch.values:
            raise PF525Error("No drive could be read; nothing to write")
        count = max(len(v) for v in batch.values.values())
        index = range(1, count + 1)
        frame = pd.DataFrame({ip: [vals.get(p) for p in index] for ip, vals in batch.values.items()},
                             index=index)
        frame.insert(0, "Name", [label(p) for p in index])
        path = Path(str(file) if str(file).lower().endswith(".xlsx") else f"{file}.xlsx")
        try:
            frame.to_excel(path)
        except PermissionError:
            alt = path.with_name(f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}.xlsx")
            self.log.warning("%s is open in another program; saving to %s instead", path, alt)
            frame.to_excel(alt)
            path = alt
        self.log.info("Parameter dump saved to %s", path)
        return DumpResult(path, batch.errors)

    def load_parameters_from_excel(self, filename, dry_run: bool = False,
                                   add_missing: bool = False) -> BatchResult:
        """Write the values in a spreadsheet to its drives. Returns ``{ip: [WriteResult]}``.

        Drives named in the sheet but not in this network are skipped (and reported
        as errors) unless ``add_missing`` is true.
        """
        changes = read_parameter_sheet(filename)
        skipped: dict[str, Exception] = {}
        for ip in list(changes):
            if ip not in self.drives:
                if add_missing:
                    self.add_drive(ip)
                else:
                    skipped[ip] = PF525Error(f"{ip} is in the spreadsheet but not in the drive list")
                    del changes[ip]
        batch = self._run(lambda d: d.write_parameters(changes[d.ip], dry_run=dry_run,
                                                       backup_dir=self.backup_dir), changes)
        batch.errors.update(skipped)
        return batch

    # ---------------------------------------------------------------- health
    def health(self, config: HealthConfig, fix: bool = False, dry_run: bool = False,
               ips: Iterable[str] | None = None) -> HealthReport:
        """Scan drives against the rule table; optionally fix (or, with ``dry_run``, plan fixes)."""
        self.log.info("Starting drive health scan")

        def scan(drive: Drive) -> list[Finding]:
            values = drive.read_parameters(REQUIRED_READS)
            findings = evaluate(drive.ip, values, config)
            fixable = [f for f in findings if f.fix]
            if fix and fixable:
                if drive_is_running(values):
                    for f in fixable:
                        f.fix_status = "skipped_running"
                else:
                    plan: dict[int, int] = {}
                    for f in fixable:
                        plan.update(f.fix)
                    results = {r.parameter: r for r in drive.write_parameters(
                        plan, dry_run=dry_run, backup_dir=self.backup_dir)}
                    for f in fixable:
                        f.fix_status = _fix_status((results[p].status for p, _ in f.fix), dry_run)
            return findings

        batch = self._run(scan, ips)
        report = HealthReport(errors=batch.errors, scanned=sorted(self._targets(ips)))
        for ip in report.scanned:
            report.findings.extend(batch.values.get(ip, []))
        for f in report.findings:
            self.log.warning("%s: %s", f.ip, f.message)
        self.log.info("Drive health scan finished")
        return report

    # --------------------------------------------------------------- autotune
    def autotune(self, ips: Iterable[str] | None = None, network: str | None = None,
                 confirm: bool = False) -> BatchResult:
        """Autotune several drives at once. Requires ``confirm=True``.

        ``network`` (e.g. ``"192.168.1.0/24"``) limits the targets to drives inside it.
        """
        targets = self._targets(ips)
        if network is not None:
            try:
                net = ipaddress.ip_network(network, strict=False)
            except ValueError as exc:
                raise ConfigError(f"Invalid network {network!r}") from exc
            targets = [ip for ip in targets if ipaddress.ip_address(ip) in net]
        if not confirm:
            raise ConfirmationRequired(
                f"Autotune starts the motor on {len(targets)} drive(s): {', '.join(targets) or 'none'}. "
                "Pass confirm=True once the machinery is clear.")
        return self._run(lambda d: d.autotune(), targets)

    # ------------------------------------------- names used by the original scripts
    @property
    def list_of_drive_objects(self):
        return self.drives

    def Dev_Add_Drive(self, ip):
        return self.add_drive(ip)

    def single_read_parameter(self, ip, parameter):
        return self.read_parameter(ip, parameter)

    def single_write_parameter(self, ip, parameter, value):
        return self.write_parameter(ip, parameter, value)

    def network_read_parameter(self, parameter):
        return self.read(parameter).values

    def network_write_parameter(self, parameter, value):
        return self.write(parameter, value)

    def network_parameter_search(self, parameter, value):
        return [[ip, v] for ip, v in self.search(parameter, value).values.items()]

    def network_parameter_dump(self, file="Drive Parameter Dump"):
        return self.dump(file)
