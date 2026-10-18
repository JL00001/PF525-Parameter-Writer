"""Drive health scanner: a table of rules evaluated against one batched read.

Checking and fixing are separate. ``evaluate`` is pure (values + config in,
findings out) so it can be unit tested without a drive; ``Network.health`` reads,
evaluates, and optionally applies the proposed fixes through the guarded
``Drive.write_parameters``.
"""
from __future__ import annotations

import csv
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .constants import P_DRIVE_STATUS, RUNNING_STATUS_MASK
from .errors import ConfigError
from .labels import label

Values = Mapping[int, int]
Fix = Sequence[tuple[int, int]]


# --------------------------------------------------------------------- config
@dataclass(frozen=True)
class HealthConfig:
    firmware_version: int
    max_speed: int                       # P44, 60 Hz == 6000
    comm_loss: int                       # P126, 1 s == 10
    subnet: tuple[int, int, int, int]    # P133-136
    en_data_out: tuple[int, int, int, int]   # P157-160
    db_and_brk_msg: bool = False
    safety_open_en: int = 0              # P105 target value
    relay_out2_sel: int | None = None    # P81 target value; None = report only

    # key -> accepted spellings (the original JSON used the first column's legacy names)
    _KEYS = {
        "firmware_version": ("firmware_version", "firmwear_verson"),
        "max_speed": ("max_speed", "drive_max_speed"),
        "comm_loss": ("comm_loss", "drive_comm_loss"),
        "subnet": ("subnet", "en_subnet_parameters"),
        "en_data_out": ("en_data_out", "en_data_out_parameters"),
        "db_and_brk_msg": ("db_and_brk_msg",),
        "safety_open_en": ("safety_open_en",),
        "relay_out2_sel": ("relay_out2_sel",),
    }

    @classmethod
    def from_dict(cls, raw: Mapping) -> "HealthConfig":
        def pick(key, required=True, default=None):
            for name in cls._KEYS[key]:
                if name in raw:
                    return raw[name]
            if required:
                raise ConfigError(f"Health config is missing '{cls._KEYS[key][0]}'")
            return default

        def integer(key, value):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"Health config '{key}' must be a whole number, got {value!r}")
            return value

        def quad(key):
            value = pick(key)
            if isinstance(value, Mapping):           # legacy {"value": [..]} form
                value = value.get("value")
            if (not isinstance(value, (list, tuple)) or len(value) != 4
                    or not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFF
                               for v in value)):
                raise ConfigError(f"Health config '{key}' must be a list of 4 whole numbers")
            return tuple(value)

        relay = pick("relay_out2_sel", required=False)
        return cls(
            firmware_version=integer("firmware_version", pick("firmware_version")),
            max_speed=integer("max_speed", pick("max_speed")),
            comm_loss=integer("comm_loss", pick("comm_loss")),
            subnet=quad("subnet"),
            en_data_out=quad("en_data_out"),
            db_and_brk_msg=bool(pick("db_and_brk_msg", required=False, default=False)),
            safety_open_en=integer("safety_open_en", pick("safety_open_en", required=False, default=0)),
            relay_out2_sel=None if relay is None else integer("relay_out2_sel", relay),
        )

    @classmethod
    def from_file(cls, path) -> "HealthConfig":
        path = Path(path)
        try:
            if path.suffix.lower() == ".toml":
                with path.open("rb") as handle:
                    raw = tomllib.load(handle)
            else:
                with path.open("r", encoding="utf-8") as handle:
                    raw = json.load(handle)
        except FileNotFoundError as exc:
            raise ConfigError(f"Health config not found: {path}") from exc
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Health config {path} is not valid: {exc}") from exc
        return cls.from_dict(raw)


# ---------------------------------------------------------------------- rules
@dataclass(frozen=True)
class Rule:
    id: str
    reads: tuple[int, ...]
    bad: Callable[[Values, HealthConfig], bool]
    message: Callable[[Values, HealthConfig], str]
    fix: Callable[[Values, HealthConfig], Fix] | None = None   # None = report only
    enabled: Callable[[HealthConfig], bool] = lambda cfg: True


def _p(parameter: int) -> str:
    return f"P{parameter:03d} {label(parameter)}"


def _fast_ramp(v: Values) -> bool:
    return v[41] < 100 or v[42] < 100


def _expect(rule_id, parameter, expected, why, fixable=True) -> Rule:
    """Rule: parameter must equal a constant (expected may be a callable of cfg)."""
    want = expected if callable(expected) else (lambda cfg, e=expected: e)
    return Rule(
        rule_id, (parameter,),
        bad=lambda v, cfg: v[parameter] != want(cfg),
        message=lambda v, cfg: f"{_p(parameter)} is {v[parameter]}, expected {want(cfg)}: {why}",
        fix=(lambda v, cfg: [(parameter, want(cfg))]) if fixable else None)


def _expect_group(rule_id, parameters, expected, why, fixable=True) -> Rule:
    """Rule: a group of parameters must equal a list of values from the config."""
    return Rule(
        rule_id, tuple(parameters),
        bad=lambda v, cfg: [v[p] for p in parameters] != list(expected(cfg)),
        message=lambda v, cfg: (f"P{parameters[0]:03d}-P{parameters[-1]:03d} "
                                f"({label(parameters[0])}..) are {[v[p] for p in parameters]}, "
                                f"expected {list(expected(cfg))}: {why}"),
        fix=(lambda v, cfg: list(zip(parameters, expected(cfg)))) if fixable else None)


RULES: tuple[Rule, ...] = (
    _expect_group("en_data_out", (157, 158, 159, 160), lambda cfg: cfg.en_data_out,
                  "wrong EN Data Out parameters"),
    _expect_group("en_subnet", (133, 134, 135, 136), lambda cfg: cfg.subnet, "wrong subnet mask"),
    Rule("en_gateway", (137, 138, 139, 140),
         bad=lambda v, cfg: [v[p] for p in (137, 138, 139, 140)] == [0, 0, 0, 0],
         message=lambda v, cfg: "EN Gateway Cfg 1-4 (P137-P140) are all 0: gateway not set"),
    _expect("reverse_disabled", 544, 1, "reverse has not been disabled", fixable=False),
    Rule("autotuned", (498,), bad=lambda v, cfg: v[498] == 0,
         message=lambda v, cfg: f"{_p(498)} is 0: drive has not been autotuned"),
    Rule("default_ramps", (41, 42), bad=lambda v, cfg: v[41] == 1000 or v[42] == 1000,
         message=lambda v, cfg: f"Accel/Decel ({v[41]}/{v[42]}) still at the default value"),
    Rule("firmware", (29,), bad=lambda v, cfg: v[29] != cfg.firmware_version,
         message=lambda v, cfg: f"{_p(29)} is {v[29]}, expected {cfg.firmware_version}: wrong firmware"),
    Rule("auto_mode", (46, 47), bad=lambda v, cfg: v[46] != 5 or v[47] != 15,
         message=lambda v, cfg: f"P046/P047 are {v[46]}/{v[47]}, expected 5/15: drive not placed in auto mode"),
    Rule("fast_ramp_no_db", (41, 42, 437), bad=lambda v, cfg: _fast_ramp(v) and v[437] == 0,
         message=lambda v, cfg: "Accel/Decel is too fast for there not to be a dynamic brake attached"),
    Rule("relay1_default", (76,), bad=lambda v, cfg: v[76] == 0,
         message=lambda v, cfg: f"{_p(76)} is still 0 (default): change to 2 or 13"),
    Rule("brk_attached", (76,), bad=lambda v, cfg: v[76] == 2,
         message=lambda v, cfg: f"{_p(76)} = 2 implies a brake (BRK) is attached to this drive",
         enabled=lambda cfg: cfg.db_and_brk_msg),
    Rule("db_attached", (437,), bad=lambda v, cfg: v[437] != 0,
         message=lambda v, cfg: f"{_p(437)} implies a dynamic braking resistor is attached",
         enabled=lambda cfg: cfg.db_and_brk_msg),
    _expect("flying_start", 545, 0, "flying start has not been disabled"),
    _expect("max_freq", 44, lambda cfg: cfg.max_speed, "wrong Maximum Freq"),
    Rule("jerk", (41, 42, 573),
         bad=lambda v, cfg: v[573] != (2 if _fast_ramp(v) else 3),
         message=lambda v, cfg: (f"{_p(573)} is {v[573]}, expected {2 if _fast_ramp(v) else 3}: "
                                 "jerk parameters incorrectly set"),
         fix=lambda v, cfg: [(573, 2 if _fast_ramp(v) else 3)]),
    _expect("comm_loss", 126, lambda cfg: cfg.comm_loss, "comm loss time not set properly"),
    _expect("static_ip", 128, 1, "drive is using BOOTP instead of a static IP"),
    *[_expect(f"digin_{p}", p, 0, "input has not been disabled") for p in (62, 63, 64, 65, 66, 67, 68)],
    Rule("relay2", (81,),
         bad=lambda v, cfg: (v[81] != cfg.relay_out2_sel) if cfg.relay_out2_sel is not None else v[81] == 0,
         message=lambda v, cfg: (f"{_p(81)} is {v[81]}, expected {cfg.relay_out2_sel}"
                                 if cfg.relay_out2_sel is not None
                                 else f"{_p(81)} is still 0 (default); set 'relay_out2_sel' in the config to fix"),
         fix=lambda v, cfg: [(81, cfg.relay_out2_sel)] if cfg.relay_out2_sel is not None else []),
    _expect("safety_open", 105, lambda cfg: cfg.safety_open_en, "safety open fault setting differs"),
)

REQUIRED_READS: tuple[int, ...] = tuple(sorted({P_DRIVE_STATUS, *(p for r in RULES for p in r.reads)}))


# ------------------------------------------------------------------- findings
@dataclass
class Finding:
    ip: str
    rule_id: str
    message: str
    observed: dict[int, int]
    fix: list[tuple[int, int]] = field(default_factory=list)
    fix_status: str = ""     # "", "planned", "fixed", "skipped_running", or a write failure status


def evaluate(ip: str, values: Values, config: HealthConfig) -> list[Finding]:
    """Apply every enabled rule to one drive's values."""
    findings = []
    for rule in RULES:
        if not rule.enabled(config) or not rule.bad(values, config):
            continue
        fix = list(rule.fix(values, config)) if rule.fix else []
        findings.append(Finding(ip, rule.id, rule.message(values, config),
                                {p: values[p] for p in rule.reads}, fix))
    return findings


def drive_is_running(values: Values) -> bool:
    return bool(values[P_DRIVE_STATUS] & RUNNING_STATUS_MASK)


@dataclass
class HealthReport:
    findings: list[Finding] = field(default_factory=list)
    errors: dict[str, Exception] = field(default_factory=dict)
    scanned: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """No findings and no unreachable drives."""
        return not self.findings and not self.errors

    @property
    def unresolved(self) -> list[Finding]:
        """Findings that are still outstanding (anything not actually fixed)."""
        return [f for f in self.findings if f.fix_status != "fixed"]

    def format(self) -> str:
        lines = []
        for ip in sorted(self.scanned):
            mine = [f for f in self.findings if f.ip == ip]
            if ip in self.errors:
                lines.append(f"{ip}: ERROR {self.errors[ip]}")
            elif not mine:
                lines.append(f"{ip}: OK")
            else:
                lines.append(f"{ip}: {len(mine)} finding(s)")
                for f in mine:
                    suffix = f"  [{f.fix_status}]" if f.fix_status else (
                        "  [fixable]" if f.fix else "")
                    lines.append(f"    - {f.message}{suffix}")
        return "\n".join(lines)

    def to_csv(self, path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ip", "rule", "message", "observed", "proposed_fix", "fix_status"])
            for f in self.findings:
                writer.writerow([f.ip, f.rule_id, f.message,
                                 json.dumps({str(k): v for k, v in f.observed.items()}),
                                 json.dumps([list(x) for x in f.fix]), f.fix_status])
            for ip, exc in self.errors.items():
                writer.writerow([ip, "error", str(exc), "", "", ""])
