import re
from dataclasses import dataclass, field
from enum import Enum

from gcode_proxy.core.logging import get_logger

logger = get_logger()


class GrblDeviceStatus(str, Enum):
    """
    Enum of known GRBL device status states.

    These are the standard device states reported by GRBL in status updates.
    The string value allows for easy comparison with parsed status strings.
    """
    IDLE = "Idle"
    RUN = "Run"
    HOLD = "Hold"
    DOOR = "Door"
    HOME = "Home"
    ALARM = "Alarm"
    CHECK = "Check"
    DISCONNECTED = "Disconnected"
    UNKNOWN = "Unknown"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class HomingStatus(Enum):
    """
    Enum for tracking the status of a homing operation.

    ESP GRBL Controllers often lose "ok"s on homing completion, due to ESP logging output
    in the serial buffer. This makes a lack of an "ok" unreliable for tracking homing completion.

    GRBL's homing command ($H) also causes the status reporting
    to transition to "Home" and then to "Idle" when complete. This enum tracks the
    homing operation state to help have a fallback detection of homing completion.

    Note that the "ok" might still come after the state transitioned back to "Idle",
    so a grace period is required to make sure it won't be missed and disposed,
    otherwise it will likely be attributed to the next command in the queue.

    refer to this enum's use in grbl_device.py

    States:
    - OFF: No homing in progress
    - QUEUED: $H command sent to device
    - COMPLETE: We detected the state transition back to "Idle", homing is complete
    """

    OFF = "off"
    QUEUED = "queued"
    COMPLETE = "complete"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value

@dataclass
class GrblDeviceState:
    """
    Represents the current status of a GRBL device.

    Parsed from the response to the `?` command:
    <Idle|MPos:3.000,3.000,0.000|FS:0,0>
    <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000>

    Attributes:
        state: Device state (Idle, Run, Hold, Door, Alarm, etc.)
        homing: Current homing operation status (OFF, QUEUED, or RUNNING)
    """
    _status: str = GrblDeviceStatus.DISCONNECTED.value
    homing: HomingStatus = field(default_factory=lambda: HomingStatus.OFF)

    @classmethod
    def parse_state_str(cls, line: str) -> str:
        """
        Parse a GRBL status report line.

        Supports both pipe and comma delimiters:
        <Idle|MPos:3.000,3.000,0.000|FS:0,0>
        <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000>

        Args:
            line: The status report line from the device.

        Returns:
            GrblDeviceState instance if parsing succeeds, None otherwise.
        """
        # Status report must be enclosed in angle brackets
        if not line.startswith("<") or not line.endswith(">"):
            return None

        # Remove brackets
        content = line[1:-1]

        # Extract the status state using regex - match word characters before | or ,
        match = re.match(r"^(\w+)[|,]", content)
        if not match:
            return GrblDeviceStatus.UNKNOWN.value

        return match.group(1)

    @classmethod
    def from_state_str(cls, line: str) -> 'GrblDeviceState':
        """
        Create a GrblDeviceState instance from a GRBL status report line.

        Args:
            line: The status report line from the device.
        """
        return cls(state=cls.parse_state_str(line))

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, status: GrblDeviceStatus) -> None:
        self._status = status.value

    def update_status(self, line: str) -> None:
        """
        Update the device state based on a GRBL status report line.

        Args:
            line: The status report line from the device.
        """
        parsed_state = GrblDeviceState.parse_state_str(line)
        self._status = parsed_state
