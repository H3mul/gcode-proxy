#!/usr/bin/env python3
"""
Test script for GCode logging functionality.

This script demonstrates and tests the gcode-log-file feature
using the TaskQueue-based architecture.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add src to path so we can import gcode_proxy
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gcode_proxy.device import GCodeDevice
from gcode_proxy.task_queue import Task, create_task_queue


class MockStreamWriter:
    """Mock StreamWriter for testing."""
    
    def __init__(self):
        self.written_data = []
        self._closed = False
    
    def write(self, data: bytes) -> None:
        self.written_data.append(data)
    
    async def drain(self) -> None:
        pass
    
    def close(self) -> None:
        self._closed = True
    
    async def wait_closed(self) -> None:
        pass
    
    def get_extra_info(self, name: str):
        if name == "peername":
            return ("127.0.0.1", 54321)
        return None


async def send_gcode_via_queue(device: GCodeDevice, gcode: str, client_address: tuple[str, int], timeout: float = 5.0) -> str:
    """
    Helper function to send a GCode command through the task queue.
    
    Args:
        device: The GCodeDevice with an attached task queue.
        gcode: The GCode command to send.
        client_address: The client address tuple.
        timeout: Timeout for waiting for response.
        
    Returns:
        The response from the device.
    """
    if not device.task_queue:
        raise RuntimeError("Device has no task queue")
    
    writer = MockStreamWriter()
    task = Task(
        command=gcode,
        client_address=client_address,
        writer=writer,
    )
    
    await device.task_queue.put(task)
    response = await task.wait_for_response(timeout=timeout)
    return response


async def test_gcode_logging():
    """Test that GCode logging works correctly."""
    print("=" * 70)
    print("GCode Logging Test")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "gcode.log"
        
        # Create a task queue
        task_queue = create_task_queue()
        
        # Create a device with logging
        print(f"\n1. Creating device with log file: {log_file}")
        device = GCodeDevice(
            task_queue=task_queue,
            gcode_log_file=str(log_file),
        )
        
        # Connect the device (this starts the task processing loop)
        print("2. Connecting device...")
        await device.connect()
        
        # Send a test gcode command via the task queue
        print("3. Sending GCode command: G28 from 127.0.0.1:54321")
        response = await send_gcode_via_queue(device, "G28", ("127.0.0.1", 54321))
        print(f"   Response: {response}")
        
        # Check that the log file was created
        assert log_file.exists(), f"Log file {log_file} was not created"
        print(f"   ✓ Log file created")
        
        # Read and display log file
        log_contents = log_file.read_text()
        print("\n4. Log file contents:")
        for line in log_contents.strip().split('\n'):
            print(f"   {line}")
        
        # Verify log contains the command and response
        assert "127.0.0.1:54321: G28" in log_contents, "Command not logged"
        assert "device: ok" in log_contents, "Response not logged"
        print("   ✓ Command and response logged correctly")
        
        # Disconnect
        await device.disconnect()
        
        # Test appending with a second device instance
        print("\n5. Testing log file appending...")
        task_queue2 = create_task_queue()
        device2 = GCodeDevice(
            task_queue=task_queue2,
            gcode_log_file=str(log_file),
        )
        await device2.connect()
        
        print("6. Sending GCode command: G1 X10 Y20 from 10.0.0.1:8080")
        response2 = await send_gcode_via_queue(device2, "G1 X10 Y20", ("10.0.0.1", 8080))
        print(f"   Response: {response2}")
        
        await device2.disconnect()
        
        # Read and display updated log file
        log_contents = log_file.read_text()
        print("\n7. Updated log file contents:")
        for line in log_contents.strip().split('\n'):
            print(f"   {line}")
        
        # Verify appending worked
        assert "10.0.0.1:8080: G1 X10 Y20" in log_contents, "Second command not logged"
        assert log_contents.count("device: ok") == 2, "Second response not logged"
        print("   ✓ Log appending works correctly")
        
        # Count lines to verify we have correct number of entries
        lines = log_contents.strip().split('\n')
        print(f"\n8. Log statistics:")
        print(f"   Total log entries: {len(lines)}")
        print(f"   Commands: {sum(1 for line in lines if ' - ' in line and not 'device:' in line)}")
        print(f"   Responses: {sum(1 for line in lines if 'device:' in line)}")
        
        print("\n" + "=" * 70)
        print("✓ All GCode logging tests passed!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_gcode_logging())