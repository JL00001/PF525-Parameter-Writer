"""Decoding of the DPI "Online Read Full" parameter record.

Pure logic only: the network read lives in ``Drive.read_parameter_info``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pycomm3

log = logging.getLogger(__name__)

# Descriptor bit layout, least-significant bit first (see the PowerFlex DPI
# parameter descriptor table; the original script's comment cites page 144).
# The fields are contiguous and add up to exactly 32 bits. Access_Level straddles
# a byte boundary, which is why this is decoded with shifts and masks rather
# than ctypes bit-fields.
DESCRIPTOR_FIELDS = (
    ("Data_Type", 3),
    ("Sign_Type", 1),
    ("Hidden", 1),
    ("Not_a_Link_Sink", 1),
    ("Not_Recallable", 1),
    ("ENUM", 1),
    ("Writable", 1),                    # 0 = read only, 1 = writable
    ("Not_Writable_When_Enabled", 1),   # 1 = cannot be written while the drive is running
    ("Instance", 1),
    ("Uses_Bit_ENUM_Mask", 1),
    ("Decimal_Point", 4),
    ("Extended_Data_Type", 3),
    ("Parameter_Exists", 1),
    ("Not_Used", 1),
    ("Formula_Links", 1),
    ("Access_Level", 3),
    ("Writable_ENUM", 1),
    ("Not_a_Link_Source", 1),
    ("Enhanced_Bit_ENUM", 1),
    ("Enhanced_ENUM", 1),
    ("Uses_DSI_Limits_Object", 1),
    ("Extended_Descriptor", 1),
    ("Always_Upload_Download", 1),
)
assert sum(width for _, width in DESCRIPTOR_FIELDS) == 32


def decode_descriptor(raw: int) -> dict[str, int]:
    """Split a 32-bit descriptor (as read from a signed DINT) into named fields."""
    raw &= 0xFFFFFFFF
    fields: dict[str, int] = {}
    shift = 0
    for name, width in DESCRIPTOR_FIELDS:
        fields[name] = (raw >> shift) & ((1 << width) - 1)
        shift += width
    return fields


def compute_real_value(internal, offset, multiplier, divisor, base, decimal_point) -> float:
    """Engineering-units value: (internal + offset) * mult * base / (div * 10^dp)."""
    if divisor == 0:
        log.warning("Parameter has a Divisor of 0; treating it as 1")
        divisor = 1
    return ((internal + offset) * multiplier * base) / (divisor * 10 ** decimal_point)


def _text(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).split(b"\x00")[0].decode("ascii", "replace").strip()
    return str(value)


def online_read_full_type():
    """pycomm3 data type for the DPI "Online Read Full" record (same layout as the original)."""
    return pycomm3.Struct(
        pycomm3.DINT("Descriptor"),
        pycomm3.DINT("Internal_Value"),
        pycomm3.DINT("Minimum_Value"),
        pycomm3.DINT("Maximum_Value"),
        pycomm3.DINT("Default_Value"),
        pycomm3.UINT("Next_Parameter"),
        pycomm3.UINT("Previous_Parameter"),
        pycomm3.n_bytes(4, "Units"),
        pycomm3.UINT("Multiplier"),
        pycomm3.UINT("Divisor"),
        pycomm3.UINT("Base"),
        pycomm3.INT("Offset"),
        pycomm3.USINT(""),
        pycomm3.USINT(""),
        pycomm3.USINT(""),
        pycomm3.USINT(""),
        pycomm3.n_bytes(16, "Parameter_Name"),
    )


@dataclass
class ParameterInfo:
    """Everything the drive reports about one parameter."""

    number: int
    raw: dict
    descriptor: dict = field(init=False)
    real_value: float = field(init=False)

    def __post_init__(self):
        self.descriptor = decode_descriptor(self.raw["Descriptor"])
        self.real_value = compute_real_value(
            self.raw["Internal_Value"], self.raw["Offset"], self.raw["Multiplier"],
            self.raw["Divisor"], self.raw["Base"], self.descriptor["Decimal_Point"])

    @property
    def name(self) -> str:
        return _text(self.raw.get("Parameter_Name", b""))

    @property
    def units(self) -> str:
        return _text(self.raw.get("Units", b""))

    @property
    def value(self) -> int:
        return self.raw["Internal_Value"]

    @property
    def writable(self) -> bool:
        return bool(self.descriptor["Parameter_Exists"] and self.descriptor["Writable"])

    @property
    def writable_when_running(self) -> bool:
        return self.writable and not self.descriptor["Not_Writable_When_Enabled"]

    def as_dict(self) -> dict:
        """Flat dict compatible with the original ``return_All_Data``."""
        data = dict(self.raw)
        data["Real_Value"] = self.real_value
        data.update(self.descriptor)
        return data
