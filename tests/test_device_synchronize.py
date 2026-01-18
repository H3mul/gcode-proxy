"""Tests for device synchronization feature in gcode processing.

Tests verify that when triggers have the synchronize flag set, a G4 P0
command is injected to force completion of prior device commands before
trigger execution.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gcode_proxy.device import GCodeDevice
from src.gcode_proxy.handlers import DefaultGCodeHandler, DefaultResponseHandler
from src.gcode_proxy.task_queue import Task, TaskQueue
from src.gcode_proxy.trigger_manager import TriggerManager
from src.gcode_proxy.triggers_config import (
    CustomTriggerConfig,
    GCodeTriggerConfig,
    TriggerBehavior,
)


class TestDeviceSynchronization:
    """Tests for device synchronization with G4 P0 injection."""

    @pytest.mark.asyncio
    async def test_synchronize_device_injects_g4_p0(self):
        """Test that _synchronize_device injects G4 P0 command."""
        device = GCodeDevice()
        
        # Mock _send and _receive
        device._send = AsyncMock()
        device._receive = AsyncMock(return_value="ok\n")
        
        response = await device._synchronize_device()
        
        # Verify G4 P0 was sent
        device._send.assert_called_once_with("G4 P0\n")
        device._receive.assert_called_once()
        assert response == "ok\n"

    @pytest.mark.asyncio
    async def test_process_task_with_synchronize_flag(self):
        """Test that _process_task injects sync command when synchronize flag is set."""
        # Create a task queue and device
        task_queue = TaskQueue()
        device = GCodeDevice(task_queue=task_queue)
        
        # Create trigger manager with synchronize flag
        trigger_config = CustomTriggerConfig(
            id="test-sync",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M9",
                behavior=TriggerBehavior.CAPTURE,
                synchronize=True,
            ),
            command="exit 0",
        )
        trigger_manager = TriggerManager([trigger_config])
        device.gcode_handler = trigger_manager
        
        # Mock device methods
        device._send = AsyncMock()
        device._receive = AsyncMock(return_value="ok\n")
        device._log_gcode = AsyncMock()
        device.response_handler.on_response = AsyncMock()
        
        # Create and process task
        mock_writer = MagicMock()
        task = Task("M9\n", ("127.0.0.1", 1234), mock_writer)
        await device._process_task(task)
        
        # Verify sync command was sent first
        send_calls = device._send.call_args_list
        # First call should be G4 P0 for synchronization
        assert send_calls[0][0][0] == "G4 P0\n"
        
        # Task should have response set
        assert task.response_future.done()

    @pytest.mark.asyncio
    async def test_process_task_without_synchronize_flag(self):
        """Test that _process_task does not inject sync when synchronize is false."""
        # Create a task queue and device
        task_queue = TaskQueue()
        device = GCodeDevice(task_queue=task_queue)
        
        # Create trigger manager without synchronize flag
        trigger_config = CustomTriggerConfig(
            id="test-no-sync",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8",
                behavior=TriggerBehavior.CAPTURE,
                synchronize=False,
            ),
            command="exit 0",
        )
        trigger_manager = TriggerManager([trigger_config])
        device.gcode_handler = trigger_manager
        
        # Mock device methods
        device._send = AsyncMock()
        device._receive = AsyncMock(return_value="ok\n")
        device._log_gcode = AsyncMock()
        device.response_handler.on_response = AsyncMock()
        
        # Create and process task with mock writer
        mock_writer = MagicMock()
        task = Task("M8\n", ("127.0.0.1", 1234), mock_writer)
        await device._process_task(task)
        
        # Verify sync command was NOT sent
        send_calls = device._send.call_args_list
        # No calls should be to G4 P0
        for call in send_calls:
            assert call[0][0] != "G4 P0\n"
        
        # Task should have response set
        assert task.response_future.done()

    @pytest.mark.asyncio
    async def test_synchronize_with_multiple_triggers_one_sync(self):
        """Test synchronization when multiple triggers match and one has sync flag."""
        # Create a task queue and device
        task_queue = TaskQueue()
        device = GCodeDevice(task_queue=task_queue)
        
        # Create trigger manager with one sync and one non-sync trigger
        configs = [
            CustomTriggerConfig(
                id="trigger-no-sync",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="trigger-sync",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        trigger_manager = TriggerManager(configs)
        device.gcode_handler = trigger_manager
        
        # Mock device methods
        device._send = AsyncMock()
        device._receive = AsyncMock(return_value="ok\n")
        device._log_gcode = AsyncMock()
        device.response_handler.on_response = AsyncMock()
        
        # Create and process task with M9 (matches both triggers, one has sync)
        mock_writer = MagicMock()
        task = Task("M9\n", ("127.0.0.1", 1234), mock_writer)
        await device._process_task(task)
        
        # Verify sync command WAS sent because one trigger has synchronize=True
        send_calls = device._send.call_args_list
        assert any(call[0][0] == "G4 P0\n" for call in send_calls), \
            "G4 P0 should be sent when any matching trigger has synchronize=True"

    @pytest.mark.asyncio
    async def test_synchronize_command_timeout_handling(self):
        """Test that synchronize timeout is properly handled."""
        device = GCodeDevice(response_timeout=1.0)
        
        # Mock _send and _receive to timeout
        device._send = AsyncMock()
        device._receive = AsyncMock(side_effect=asyncio.TimeoutError())
        
        # Should raise TimeoutError
        with pytest.raises(asyncio.TimeoutError):
            await device._synchronize_device()

    @pytest.mark.asyncio
    async def test_synchronize_integration_with_forward_behavior(self):
        """Test synchronization with FORWARD behavior trigger."""
        # Create a task queue and device
        task_queue = TaskQueue()
        device = GCodeDevice(task_queue=task_queue)
        
        # Create trigger manager with FORWARD behavior and synchronize flag
        trigger_config = CustomTriggerConfig(
            id="test-sync-forward",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M9",
                behavior=TriggerBehavior.FORWARD,
                synchronize=True,
            ),
            command="exit 0",
        )
        trigger_manager = TriggerManager([trigger_config])
        device.gcode_handler = trigger_manager
        
        # Mock device methods
        device._send = AsyncMock()
        device._receive = AsyncMock(return_value="ok\n")
        device._log_gcode = AsyncMock()
        device.response_handler.on_response = AsyncMock()
        
        # Create and process task with mock writer
        mock_writer = MagicMock()
        task = Task("M9\n", ("127.0.0.1", 1234), mock_writer)
        await device._process_task(task)
        
        # Verify sync command was sent first
        send_calls = device._send.call_args_list
        assert send_calls[0][0][0] == "G4 P0\n"
        # Then the actual M9 command
        assert send_calls[1][0][0] == "M9\n"
        
        # Task should have device response
        assert task.response_future.done()

    @pytest.mark.asyncio
    async def test_handler_result_includes_synchronize_flag(self):
        """Test that handler result includes synchronize flag in metadata."""
        # Create trigger manager with synchronize flag
        trigger_config = CustomTriggerConfig(
            id="test-sync",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M9",
                behavior=TriggerBehavior.CAPTURE,
                synchronize=True,
            ),
            command="exit 0",
        )
        trigger_manager = TriggerManager([trigger_config])
        
        # Call on_gcode with matching command
        result = await trigger_manager.on_gcode("M9\n", ("127.0.0.1", 1234))
        
        # Verify result includes synchronize flag
        assert "should_synchronize" in result
        assert result["should_synchronize"] is True

    @pytest.mark.asyncio
    async def test_handler_result_synchronize_false_by_default(self):
        """Test that handler result has synchronize=False when not set."""
        trigger_manager = TriggerManager()
        
        # Call on_gcode with non-matching command
        result = await trigger_manager.on_gcode("G28\n", ("127.0.0.1", 1234))
        
        # Verify result has synchronize flag as False
        assert "should_synchronize" in result
        assert result["should_synchronize"] is False