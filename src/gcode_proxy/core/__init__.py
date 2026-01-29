"""
Core package - Contains core utilities and infrastructure.

This package provides:
- Task: Task queue and task types (GCodeTask, ShellTask)
- Utils: Utility functions for GRBL communication
- ConnectionManager: TCP client connection management
- Config: Configuration loading and management
- Handlers: Request/response handlers
- Server: TCP server implementation
- Service: Service management
- Interface: Serial protocol interface
- Logging: Logging utilities
"""

from .task import Task, GCodeTask, ShellTask, create_task_queue, empty_queue
from .utils import (
    SerialConnectionError,
    SerialDeviceNotFoundError,
    detect_grbl_soft_reset_command,
    find_serial_port_by_usb_id,
    wait_for_device,
)
from .connection_manager import ConnectionManager
from .config import Config
from .logging import log_gcode_sent

__all__ = [
    "Task",
    "GCodeTask",
    "ShellTask",
    "create_task_queue",
    "empty_queue",
    "SerialConnectionError",
    "SerialDeviceNotFoundError",
    "detect_grbl_soft_reset_command",
    "find_serial_port_by_usb_id",
    "wait_for_device",
    "ConnectionManager",
    "Config",
    "log_gcode_sent",
]
