"""
Extensible handlers for GCode and serial response processing.

These handlers provide hooks for custom processing of incoming GCode commands
and serial responses. Future implementations can extend these to trigger
external scripts or perform custom actions based on the data.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable


class GCodeHandler(ABC):
    """
    Abstract base class for handling incoming GCode commands.
    
    Extend this class to implement custom processing of GCode commands
    before they are forwarded to the serial device.
    """
    
    @abstractmethod
    async def on_gcode(self, gcode: str, client_address: tuple[str, int]) -> None:
        """
        Called after a GCode command has been sent to the serial device.
        
        Args:
            gcode: The GCode command that was sent.
            client_address: Tuple of (host, port) identifying the client.
        """
        pass


class ResponseHandler(ABC):
    """
    Abstract base class for handling serial responses from the device.
    
    Extend this class to implement custom processing of responses
    before they are sent back to the TCP client.
    """
    
    @abstractmethod
    async def on_response(
        self, response: str, gcode: str, client_address: tuple[str, int]
    ) -> None:
        """
        Called after a response has been sent to the TCP client.
        
        Args:
            response: The response that was sent.
            client_address: Tuple of (host, port) identifying the client.
        """
        pass


class DefaultGCodeHandler(GCodeHandler):
    """
    Default pass-through GCode handler.
    
    This handler simply passes GCode commands through without modification.
    """
    
    async def on_gcode(self, gcode: str, client_address: tuple[str, int]) -> None:
        """No-op after sending."""
        pass


class DefaultResponseHandler(ResponseHandler):
    """
    Default pass-through response handler.
    
    This handler simply passes responses through without modification.
    """
    
    async def on_response(
        self, response: str, gcode: str, client_address: tuple[str, int]
    ) -> None:
        """No-op after sending."""
        pass


# Type aliases for callback-based handlers (alternative to class-based)
GCodeCallback = Callable[[str, tuple[str, int]], Awaitable[None]]
ResponseCallback = Callable[[str, str, tuple[str, int]], Awaitable[None]]


class CallbackGCodeHandler(GCodeHandler):
    """
    GCode handler that uses callback functions.
    
    This provides a simpler alternative to subclassing for simple use cases.
    """
    
    def __init__(
        self,
        on_gcode: GCodeCallback | None = None,
    ):
        """
        Initialize with optional callback functions.
        
        Args:
            on_received: Callback for when GCode is received.
            on_sent: Callback for when GCode is sent.
        """
        self._on_gcode = on_gcode
    
    async def on_gcode(self, gcode: str, client_address: tuple[str, int]) -> None:
        if self._on_gcode:
            await self._on_gcode(gcode, client_address)


class CallbackResponseHandler(ResponseHandler):
    """
    Response handler that uses callback functions.
    
    This provides a simpler alternative to subclassing for simple use cases.
    """
    
    def __init__(
        self,
        on_response: ResponseCallback | None = None,
    ):
        """
        Initialize with optional callback functions.
        
        Args:
            on_received: Callback for when a response is received.
            on_sent: Callback for when a response is sent.
        """
        self._on_response = on_response
    
    async def on_response(
        self, response: str, gcode: str, client_address: tuple[str, int]
    ) -> None:
        if self._on_response:
            await self._on_response(response, gcode, client_address)
