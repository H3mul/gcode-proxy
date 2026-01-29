"""Standalone test for GrblDeviceState parsing functionality."""

from dataclasses import dataclass, field


@dataclass
class GrblDeviceState:
    """
    Represents the current status of a GRBL device.
    
    Parsed from the response to the `?` command:
    <Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>
    
    Attributes:
        state: Device state (Idle, Run, Hold, Door, Alarm, etc.)
        mpos: Machine position as (X, Y, Z) tuple in mm or inches
        wpos: Work position as (X, Y, Z) tuple in mm or inches
        buf: Number of motions queued in GRBL's planner buffer
        rx: Number of characters queued in GRBL's serial RX buffer
    """
    state: str = "Unknown"
    mpos: tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    wpos: tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    buf: int = 0
    rx: int = 0
    
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


def test_parse_status_report():
    """Test parsing a GRBL status report."""
    line = "<Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Idle"
    assert state.mpos == (0.0, 0.0, 0.0)
    assert state.wpos == (0.0, 0.0, 0.0)
    assert state.buf == 0
    assert state.rx == 0
    print("✓ Test 1: Basic status report parsing passed")


def test_parse_status_report_with_values():
    """Test parsing a GRBL status report with non-zero values."""
    line = "<Run,MPos:10.500,20.250,5.125,WPos:10.500,20.250,5.125,Buf:5,RX:10>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Run"
    assert state.mpos == (10.5, 20.25, 5.125)
    assert state.wpos == (10.5, 20.25, 5.125)
    assert state.buf == 5
    assert state.rx == 10
    print("✓ Test 2: Status report with values parsing passed")


def test_parse_status_report_hold():
    """Test parsing a GRBL status report with Hold state."""
    line = "<Hold,MPos:15.000,25.000,0.000,WPos:0.000,0.000,0.000,Buf:10,RX:25>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Hold"
    assert state.mpos == (15.0, 25.0, 0.0)
    assert state.wpos == (0.0, 0.0, 0.0)
    assert state.buf == 10
    assert state.rx == 25
    print("✓ Test 3: Hold state parsing passed")


def test_parse_invalid_line_no_brackets():
    """Test that non-status report lines return None."""
    line = "ok"
    state = GrblDeviceState.parse(line)
    assert state is None
    print("✓ Test 4: Invalid line (no brackets) returns None")


def test_parse_invalid_format():
    """Test that malformed status reports are handled gracefully."""
    line = "<Idle,InvalidFormat>"
    state = GrblDeviceState.parse(line)
    
    # Should still create state with default values for unparseable fields
    assert state is not None
    assert state.state == "Idle"
    assert state.mpos == (0.0, 0.0, 0.0)  # defaults
    assert state.wpos == (0.0, 0.0, 0.0)  # defaults
    print("✓ Test 5: Malformed status report handled gracefully")


def test_default_state():
    """Test default GrblDeviceState creation."""
    state = GrblDeviceState()
    
    assert state.state == "Unknown"
    assert state.mpos == (0.0, 0.0, 0.0)
    assert state.wpos == (0.0, 0.0, 0.0)
    assert state.buf == 0
    assert state.rx == 0
    print("✓ Test 6: Default state creation passed")


def test_parse_alarm_state():
    """Test parsing a GRBL status report with Alarm state."""
    line = "<Alarm,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000,Buf:0,RX:0>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Alarm"
    assert state.mpos == (0.0, 0.0, 0.0)
    print("✓ Test 7: Alarm state parsing passed")


def test_parse_door_state():
    """Test parsing a GRBL status report with Door state."""
    line = "<Door,MPos:5.000,10.000,2.500,WPos:5.000,10.000,2.500,Buf:3,RX:7>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Door"
    assert state.mpos == (5.0, 10.0, 2.5)
    assert state.wpos == (5.0, 10.0, 2.5)
    assert state.buf == 3
    assert state.rx == 7
    print("✓ Test 8: Door state parsing passed")


def test_parse_negative_coordinates():
    """Test parsing a GRBL status report with negative coordinates."""
    line = "<Idle,MPos:-5.500,-10.250,-2.125,WPos:-5.500,-10.250,-2.125,Buf:0,RX:0>"
    state = GrblDeviceState.parse(line)
    
    assert state is not None
    assert state.state == "Idle"
    assert state.mpos == (-5.5, -10.25, -2.125)
    assert state.wpos == (-5.5, -10.25, -2.125)
    print("✓ Test 9: Negative coordinates parsing passed")


if __name__ == "__main__":
    test_parse_status_report()
    test_parse_status_report_with_values()
    test_parse_status_report_hold()
    test_parse_invalid_line_no_brackets()
    test_parse_invalid_format()
    test_default_state()
    test_parse_alarm_state()
    test_parse_door_state()
    test_parse_negative_coordinates()
    print("\n✅ All 9 tests passed!")