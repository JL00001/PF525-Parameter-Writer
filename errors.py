"""Exceptions raised by the pf525 package.

None of these log in ``__init__``; callers decide whether and where to log.
"""


class PF525Error(Exception):
    """Base class for every error raised by this package."""


class CommError(PF525Error):
    """The drive could not be reached (network / EtherNet/IP session failure)."""


class DeviceStateConflict(PF525Error):
    """The drive refused the request because of its current state."""

    def __init__(self, message="The drive is not in the correct state. Inhibit the drive in the "
                               "I/O tree or place the whole controller in program mode."):
        super().__init__(message)


class DriveBusyError(PF525Error):
    """An operation that needs a stopped drive was attempted while it was running."""


class WriteVerifyError(PF525Error):
    """A parameter was written but the read-back value did not match."""


class ConfigError(PF525Error):
    """A configuration file (health config, spreadsheet) is invalid."""


class ConfirmationRequired(PF525Error):
    """A destructive bulk operation was requested without explicit confirmation."""
