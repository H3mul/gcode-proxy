"""Test GrblDeviceState parsing functionality."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gcode_proxy.device import GrblDeviceState


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


if __name__ == "__main__":
    test_parse_status_report()
    test_parse_status_report_with_values()
    test_parse_status_report_hold()
    test_parse_invalid_line_no_brackets()
    test_parse_invalid_format()
    test_default_state()
    print("\n✅ All tests passed!")
