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
    <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>
    <Idle|MPos:3.000,3.000,0.000|FS:0,0>

    Attributes:
        state: Device state (Idle, Run, Hold, Door, Alarm, etc.)
        mpos: Machine position as (X, Y, Z) tuple in mm or inches
        wpos: Work position as (X, Y, Z) tuple in mm or inches
        buf: Number of motions queued in GRBL's planner buffer
        rx: Number of characters queued in GRBL's serial RX buffer
        homing: Current homing operation status (OFF, QUEUED, or RUNNING)
    """
    state: str = "Unknown"
    mpos: tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    wpos: tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    buf: int = 0
    rx: int = 0
    homing: HomingStatus = field(default_factory=lambda: HomingStatus.OFF)

    @classmethod
    def parse(cls, line: str) -> "GrblDeviceState | None":
        """
        Parse a GRBL status report line.

        Expected format: <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>

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

        # Split by comma, but be careful with coordinates
        parts = content.split(",")
        if len(parts) < 1:
            return None

        state = parts[0]
        mpos = (0.0, 0.0, 0.0)
        wpos = (0.0, 0.0, 0.0)
        buf = 0
        rx = 0

        # Parse remaining parts - handle MPos and WPos with their coordinates
        i = 1
        while i < len(parts):
            part = parts[i].strip()

            if part.startswith("MPos:"):
                # MPos:x,y,z - x is in current part, y and z in next 2 parts
                try:
                    x = float(part[5:])
                    y = float(parts[i + 1].strip()) if i + 1 < len(parts) else 0.0
                    z = float(parts[i + 2].strip()) if i + 2 < len(parts) else 0.0
                    mpos = (x, y, z)
                    i += 2  # Skip the next 2 parts we just processed
                except (ValueError, IndexError):
                    pass

            elif part.startswith("WPos:"):
                # WPos:x,y,z - x is in current part, y and z in next 2 parts
                try:
                    x = float(part[5:])
                    y = float(parts[i + 1].strip()) if i + 1 < len(parts) else 0.0
                    z = float(parts[i + 2].strip()) if i + 2 < len(parts) else 0.0
                    wpos = (x, y, z)
                    i += 2  # Skip the next 2 parts we just processed
                except (ValueError, IndexError):
                    pass

            elif part.startswith("Buf:"):
                try:
                    buf = int(part[4:])
                except ValueError:
                    pass

            elif part.startswith("RX:"):
                try:
                    rx = int(part[3:])
                except ValueError:
                    pass

            i += 1

        return cls(state=state, mpos=mpos, wpos=wpos, buf=buf, rx=rx)

    @classmethod
    def parse_state_str(cls, line: str) -> str:
        """
        Parse a GRBL status report line and extract just the state.

        Supports both pipe and comma delimiters:
        <Idle|MPos:3.000,3.000,0.000|FS:0,0>
        <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000>

        Args:
            line: The status report line from the device.

        Returns:
            Status state string if parsing succeeds, "Unknown" otherwise.
        """
        # Status report must be enclosed in angle brackets
        if not line.startswith("<") or not line.endswith(">"):
            return GrblDeviceStatus.UNKNOWN.value

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
        return self.state

    @status.setter
    def status(self, status: GrblDeviceStatus) -> None:
        self.state = status.value

    def update_status(self, line: str) -> None:
        """
        Update the device state based on a GRBL status report line.

        Args:
            line: The status report line from the device.
        """
        parsed_state = GrblDeviceState.parse_state_str(line)
        self.state = parsed_state