"""
Hard-stop exceptions. Every hard stop in the autonomy ladder (MVP FRD §5.13,
Adaptive FRD §5.10) raises HardStop with a stable `code` so tests, the
ledger, and the operator console can key off it without string matching.
"""
from __future__ import annotations


class RouterError(Exception):
    """Base class for all Intelligence Router errors."""


class HardStop(RouterError):
    """
    Raised for any action the autonomy ladder marks 'Blocked'. A HardStop
    must never be caught and silently worked around -- it is always either
    surfaced as a ledgered refusal or allowed to propagate.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


class ValidationError(RouterError):
    """Malformed input -- distinct from a HardStop, which is a policy refusal."""
