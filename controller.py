"""Find the processor slot of a Logix controller."""
from __future__ import annotations

import logging
from typing import Callable

import pycomm3

from .errors import PF525Error

PLC_PRODUCT_TYPE = "Programmable Logic Controller"


class Controller:
    def __init__(self, ip: str, log: logging.Logger | None = None, slots=range(4),
                 choose: Callable[[list[int]], int] | None = None):
        """``choose`` picks a slot when several look like processors (default: ask on the console)."""
        self.ip = ip
        self.log = log or logging.getLogger(f"pf525.controller.{ip}")
        self.slot = self._find_processor_slot(slots, choose or self._ask)

    def _find_processor_slot(self, slots, choose) -> int:
        candidates = []
        pycomm_log = logging.getLogger("pycomm3.cip_driver.CIPDriver")
        was_disabled = pycomm_log.disabled
        pycomm_log.disabled = True              # empty slots make pycomm3 log scary errors
        try:
            with pycomm3.CIPDriver(self.ip) as driver:
                for slot in slots:
                    try:
                        info = driver.get_module_info(slot)
                    except pycomm3.exceptions.ResponseError:
                        continue
                    if info and info.get("product_type") == PLC_PRODUCT_TYPE:
                        candidates.append(slot)
        finally:
            pycomm_log.disabled = was_disabled
        if not candidates:
            raise PF525Error(f"No processor found in slots {list(slots)} of {self.ip}")
        if len(candidates) == 1:
            return candidates[0]
        self.log.warning("More than one possible processor slot: %s", candidates)
        return choose(candidates)

    @staticmethod
    def _ask(candidates: list[int]) -> int:
        while True:
            answer = input(f"Which slot holds the processor? {candidates}: ").strip()
            if answer.isdigit() and int(answer) in candidates:
                return int(answer)
            print("That is not one of the listed slots.")
