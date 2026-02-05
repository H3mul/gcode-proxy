"""
Tests for device discovery and polling functionality.

These tests verify that the device discovery properly waits for device
availability matching current implementation.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

import serial

from gcode_proxy.core.utils import (
    SerialDeviceNotFoundError,
    wait_for_device,
)


class TestWaitForDevice(unittest.TestCase):
    """Test the wait_for_device function."""

    def test_wait_for_device_requires_usb_id_or_dev_path(self):
        """Should raise ValueError if neither usb_id nor dev_path provided."""
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(wait_for_device())
        self.assertIn("Must specify either usb_id or dev_path", str(ctx.exception))

    @patch("serial.Serial")
    def test_wait_for_device_with_dev_path_immediate_success(self, mock_serial):
        """Should return immediately if device path exists/opens."""
        # Setup mock context manager
        mock_serial.return_value.__enter__.return_value = MagicMock()

        result = asyncio.run(
            wait_for_device(dev_path="/dev/ttyACM0", initialization_delay=0.0)
        )
        self.assertEqual(result, "/dev/ttyACM0")
        mock_serial.assert_called_with("/dev/ttyACM0")

    @patch("serial.Serial")
    def test_wait_for_device_with_dev_path_retry(self, mock_serial):
        """Should retry if device path is not initially available."""
        # Fail twice then succeed
        success_mock = MagicMock()
        success_mock.__enter__.return_value = MagicMock()
        success_mock.__exit__.return_value = None
        
        mock_serial.side_effect = [
            serial.SerialException("Not found"),
            FileNotFoundError("Not found"),
            success_mock,
        ]

        async def run_test():
            return await wait_for_device(
                dev_path="/dev/ttyACM0", poll_interval=0.01, initialization_delay=0.0
            )

        result = asyncio.run(run_test())
        self.assertEqual(result, "/dev/ttyACM0")
        self.assertEqual(mock_serial.call_count, 3)

    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_with_usb_id_immediate_success(self, mock_find_port):
        """Should return immediately if USB device is found."""
        mock_find_port.return_value = "/dev/ttyUSB0"
        result = asyncio.run(
            wait_for_device(usb_id="303a:4001", initialization_delay=0.0)
        )
        self.assertEqual(result, "/dev/ttyUSB0")
        mock_find_port.assert_called_with("303a:4001")

    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_with_usb_id_retry(self, mock_find_port):
        """Should retry if USB device is not initially found."""
        # Fail twice then succeed
        mock_find_port.side_effect = [
            SerialDeviceNotFoundError("Not found"),
            SerialDeviceNotFoundError("Not found"),
            "/dev/ttyUSB0",
        ]

        async def run_test():
            return await wait_for_device(
                usb_id="303a:4001", poll_interval=0.01, initialization_delay=0.0
            )

        result = asyncio.run(run_test())
        self.assertEqual(result, "/dev/ttyUSB0")
        self.assertEqual(mock_find_port.call_count, 3)

    def test_wait_for_device_handles_cancellation(self):
        """Should raise CancelledError when polling task is cancelled."""

        async def cancel_after_delay():
            task = asyncio.create_task(
                wait_for_device(
                    usb_id="303a:4001",  # Will loop forever finding nothing (mocked)
                    poll_interval=0.01,
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return True
            except Exception:
                return False
            return False

        # Mock find_serial_port_by_usb_id to fail continuously
        with patch(
            "gcode_proxy.core.utils.find_serial_port_by_usb_id",
            side_effect=SerialDeviceNotFoundError("Not found"),
        ):
            result = asyncio.run(cancel_after_delay())
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()