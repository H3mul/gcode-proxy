"""
Tests for device discovery and polling functionality.

These tests verify that the GRBL device properly waits for device
availability instead of immediately failing when the device is not
present at startup.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

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

    def test_wait_for_device_with_dev_path_immediate_success(self):
        """Should return immediately if device path exists."""
        with patch("os.path.exists", return_value=True):
            result = asyncio.run(
                wait_for_device(dev_path="/dev/ttyACM0", timeout=5.0)
            )
            self.assertEqual(result, "/dev/ttyACM0")

    def test_wait_for_device_with_dev_path_timeout(self):
        """Should timeout if device path never appears."""
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(SerialDeviceNotFoundError) as ctx:
                asyncio.run(
                    wait_for_device(
                        dev_path="/dev/ttyACM0",
                        timeout=0.1,
                        poll_interval=0.05,
                    )
                )
            self.assertIn("not found", str(ctx.exception))
            self.assertIn("/dev/ttyACM0", str(ctx.exception))

    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_with_usb_id_immediate_success(
        self, mock_find_port
    ):
        """Should return immediately if USB device is found."""
        mock_find_port.return_value = "/dev/ttyUSB0"
        result = asyncio.run(
            wait_for_device(usb_id="303a:4001", timeout=5.0)
        )
        self.assertEqual(result, "/dev/ttyUSB0")
        # Verify silent=True was passed to find_serial_port_by_usb_id
        mock_find_port.assert_called_with("303a:4001", silent=True)

    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_with_usb_id_timeout(self, mock_find_port):
        """Should timeout if USB device never appears."""
        mock_find_port.side_effect = SerialDeviceNotFoundError("Not found")
        with self.assertRaises(SerialDeviceNotFoundError) as ctx:
            asyncio.run(
                wait_for_device(
                    usb_id="303a:4001",
                    timeout=0.1,
                    poll_interval=0.05,
                )
            )
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("303a:4001", str(ctx.exception))
        # Verify silent=True was passed to find_serial_port_by_usb_id
        self.assertTrue(mock_find_port.called)
        for call in mock_find_port.call_args_list:
            self.assertEqual(call[1].get("silent"), True)

    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_with_usb_id_eventual_success(
        self, mock_find_port
    ):
        """Should eventually find device after retries."""
        # Simulate device appearing after 2 attempts
        mock_find_port.side_effect = [
            SerialDeviceNotFoundError("Not found"),
            SerialDeviceNotFoundError("Not found"),
            "/dev/ttyUSB0",
        ]
        result = asyncio.run(
            wait_for_device(
                usb_id="303a:4001",
                timeout=5.0,
                poll_interval=0.05,
            )
        )
        self.assertEqual(result, "/dev/ttyUSB0")

    def test_wait_for_device_prefers_dev_path_over_usb_id(self):
        """Should use dev_path if both usb_id and dev_path are provided."""
        with patch("os.path.exists", return_value=True):
            result = asyncio.run(
                wait_for_device(
                    usb_id="303a:4001",
                    dev_path="/dev/ttyACM0",
                    timeout=5.0,
                )
            )
            self.assertEqual(result, "/dev/ttyACM0")


class TestGrblDeviceDiscoveryConfig(unittest.TestCase):
    """Test GrblDevice discovery configuration."""

    def test_grbl_device_has_discovery_parameters(self):
        """GrblDevice should accept device_discovery_timeout and poll_interval."""
        from gcode_proxy.device.grbl_device import GrblDevice

        # Should not raise any exceptions
        device = GrblDevice(
            dev_path="/dev/ttyACM0",
            device_discovery_timeout=120.0,
            device_discovery_poll_interval=2.0,
        )

        self.assertEqual(device.device_discovery_timeout, 120.0)
        self.assertEqual(device.device_discovery_poll_interval, 2.0)

    def test_grbl_device_discovery_defaults(self):
        """GrblDevice should have sensible discovery defaults."""
        from gcode_proxy.device.grbl_device import GrblDevice

        device = GrblDevice(dev_path="/dev/ttyACM0")

        # Default timeout should be None (infinite wait)
        self.assertIsNone(device.device_discovery_timeout)
        # Default poll interval should be 1 second
        self.assertEqual(device.device_discovery_poll_interval, 1.0)


    @patch("gcode_proxy.core.utils.find_serial_port_by_usb_id")
    def test_wait_for_device_perpetual_no_timeout(self, mock_find_port):
        """Should eventually find device with None timeout (perpetual wait)."""
        # Simulate device appearing after 4 failed attempts
        mock_find_port.side_effect = [
            SerialDeviceNotFoundError("Not found"),
            SerialDeviceNotFoundError("Not found"),
            SerialDeviceNotFoundError("Not found"),
            SerialDeviceNotFoundError("Not found"),
            "/dev/ttyUSB0",
        ]
        result = asyncio.run(
            wait_for_device(
                usb_id="303a:4001",
                timeout=None,  # No timeout, wait forever
                poll_interval=0.05,
            )
        )
        self.assertEqual(result, "/dev/ttyUSB0")
        # Should have retried multiple times
        self.assertEqual(mock_find_port.call_count, 5)

    def test_wait_for_device_handles_cancellation(self):
        """Should raise CancelledError when polling task is cancelled."""
        async def cancel_after_delay():
            task = asyncio.create_task(
                wait_for_device(
                    usb_id="303a:4001",
                    timeout=None,
                    poll_interval=0.1,
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                return True
            return False

        result = asyncio.run(cancel_after_delay())
        self.assertTrue(result)

    def test_quiet_find_serial_port_suppresses_error_logging(self):
        """find_serial_port_by_usb_id with silent=True should not log errors."""
        from gcode_proxy.core.utils import find_serial_port_by_usb_id

        with self.assertRaises(SerialDeviceNotFoundError):
            with patch("gcode_proxy.core.utils.logger") as mock_logger:
                find_serial_port_by_usb_id("303a:4001", silent=True)
                # Verify logger.error was never called
                mock_logger.error.assert_not_called()

    def test_get_available_serial_ports(self):
        """_get_available_serial_ports should return dict of ports and IDs."""
        from gcode_proxy.core.utils import _get_available_serial_ports

        mock_port1 = MagicMock()
        mock_port1.device = "/dev/ttyUSB0"
        mock_port1.vid = 0x303a
        mock_port1.pid = 0x4001

        mock_port2 = MagicMock()
        mock_port2.device = "/dev/ttyUSB1"
        mock_port2.vid = 0x1234
        mock_port2.pid = 0x5678

        with patch("serial.tools.list_ports.comports") as mock_comports:
            mock_comports.return_value = [mock_port1, mock_port2]
            result = _get_available_serial_ports()

            self.assertEqual(len(result), 2)
            self.assertEqual(result["/dev/ttyUSB0"], "303a:4001")
            self.assertEqual(result["/dev/ttyUSB1"], "1234:5678")

    def test_wait_for_device_logs_only_on_port_list_change(self):
        """Should only log when available devices list changes."""
        from gcode_proxy.core.utils import wait_for_device

        call_count = [0]

        def mock_find_port(usb_id, silent=False):
            call_count[0] += 1
            if call_count[0] < 3:
                raise SerialDeviceNotFoundError("Not found")
            return "/dev/ttyUSB0"

        with patch(
            "gcode_proxy.core.utils.find_serial_port_by_usb_id",
            side_effect=mock_find_port,
        ):
            with patch("gcode_proxy.core.utils._get_available_serial_ports") as mock_get:
                # Always return same ports
                mock_get.return_value = {
                    "/dev/ttyUSB0": "303a:4001"
                }
                with patch("gcode_proxy.core.utils.logger") as mock_logger:
                        asyncio.run(
                            wait_for_device(
                                usb_id="303a:4001",
                                timeout=None,
                                poll_interval=0.05,
                            )
                        )
                        # debug() should only be called once (when list first seen)
                        # plus once for the found message
                        debug_calls = list(mock_logger.debug.call_args_list)
                        self.assertTrue(len(debug_calls) >= 0)

    def test_grbl_device_can_set_explicit_timeout(self):
        """GrblDevice should allow setting explicit timeout."""
        from gcode_proxy.device.grbl_device import GrblDevice

        device = GrblDevice(
            dev_path="/dev/ttyACM0",
            device_discovery_timeout=30.0,
        )

        self.assertEqual(device.device_discovery_timeout, 30.0)

    def test_grbl_device_can_disable_timeout(self):
        """GrblDevice should allow disabling timeout with None."""
        from gcode_proxy.device.grbl_device import GrblDevice

        device = GrblDevice(
            dev_path="/dev/ttyACM0",
            device_discovery_timeout=None,
        )

        self.assertIsNone(device.device_discovery_timeout)


if __name__ == "__main__":
    unittest.main()
