"""GCode Proxy Server - A middleman between gcode stream sources and USB devices."""

__version__ = "0.1.0"
__author__ = "GCode Proxy Team"

from .device import GCodeDevice, GCodeSerialDevice
from .service import GCodeProxyService
from .server import GCodeServer
from .handlers import GCodeHandler, ResponseHandler
from .task_queue import Task, TaskQueue, create_task_queue
from .utils import SerialDeviceNotFoundError, SerialConnectionError

__all__ = [
    "GCodeDevice",
    "GCodeSerialDevice",
    "GCodeProxyService",
    "GCodeServer",
    "GCodeHandler",
    "ResponseHandler",
    "Task",
    "TaskQueue",
    "create_task_queue",
    "SerialDeviceNotFoundError",
    "SerialConnectionError",
    "__version__",
]
