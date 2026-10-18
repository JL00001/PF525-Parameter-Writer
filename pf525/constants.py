"""CIP / DPI constants for the PowerFlex 525.

The *types* here (bytes vs int) deliberately mirror the calls the original
scripts made against real hardware, so that pycomm3 builds identical requests.
"""

# DPI Parameter object
PARAM_CLASS = b'\x93'
ATTR_PARAM_COUNT = b'\x00'        # instance 0, attribute 0 -> number of parameters
ATTR_PARAM_VALUE = b'\x09'        # attribute 9 -> parameter value
ATTR_ONLINE_READ_FULL = 7         # attribute 7 -> descriptor/min/max/default/scaling/name

# DPI scattered services (instance 0 of the parameter class)
SVC_SCATTERED_READ = 0x32
SVC_SCATTERED_WRITE = 0x34
SCATTER_CHUNK = 64                # max (parameter, value) pairs per scattered request

# Register object (logic command / comm timeout)
LOGIC_COMMAND_INSTANCE = b'\x14'
LOGIC_COMMAND_ATTR = b'\x04'
LOGIC_TIMEOUT_INSTANCE = b'\x00'
LOGIC_TIMEOUT_ATTR = b'\x64'

# Logic command bit patterns used by autotune
LOGIC_RELEASE = 0
LOGIC_STOP = 1
LOGIC_START = 2
LOGIC_CLEAR_FAULTS = 8

# Parameter 6 (Drive Status). The original health scanner treated bit 0 == 1 as
# "drive running / not safe to write". Confirm this against the PF525 manual.
P_DRIVE_STATUS = 6
RUNNING_STATUS_MASK = 0x0001

# Parameters touched by autotune
P_AUTOTUNE = 40
P_START_SOURCE = 46
P_SPEED_REFERENCE = 47
P_MOTOR_RR = 498

DEFAULT_BACKUP_DIR = "pf525_backups"
