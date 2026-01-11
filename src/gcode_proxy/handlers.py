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
    async def on_gcode_received(self, gcode: str, client_address: tuple[str, int]) -> str:
        """
        Called when a GCode command is received from a TCP client.
        
        Args:
            gcode: The raw GCode command string received.
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            The (possibly modified) GCode command to forward to the device.
            Return the original gcode to pass through unchanged.
        """
        pass
    
    @abstractmethod
    async def on_gcode_sent(self, gcode: str, client_address: tuple[str, int]) -> None:
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
    async def on_response_received(
        self, response: str, original_gcode: str, client_address: tuple[str, int]
    ) -> str:
        """
        Called when a response is received from the serial device.
        
        Args:
            response: The raw response string from the device.
            original_gcode: The GCode command that triggered this response.
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            The (possibly modified) response to send back to the client.
            Return the original response to pass through unchanged.
        """
        pass
    
    @abstractmethod
    async def on_response_sent(
        self, response: str, client_address: tuple[str, int]
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
    
    async def on_gcode_received(self, gcode: str, client_address: tuple[str, int]) -> str:
        """Pass through the GCode command unchanged."""
        return gcode
    
    async def on_gcode_sent(self, gcode: str, client_address: tuple[str, int]) -> None:
        """No-op after sending."""
        pass


class DefaultResponseHandler(ResponseHandler):
    """
    Default pass-through response handler.
    
    This handler simply passes responses through without modification.
    """
    
    async def on_response_received(
        self, response: str, original_gcode: str, client_address: tuple[str, int]
    ) -> str:
        """Pass through the response unchanged."""
        return response
    
    async def on_response_sent(
        self, response: str, client_address: tuple[str, int]
    ) -> None:
        """No-op after sending."""
        pass


# Type aliases for callback-based handlers (alternative to class-based)
GCodeReceivedCallback = Callable[[str, tuple[str, int]], Awaitable[str]]
GCodeSentCallback = Callable[[str, tuple[str, int]], Awaitable[None]]
ResponseReceivedCallback = Callable[[str, str, tuple[str, int]], Awaitable[str]]
ResponseSentCallback = Callable[[str, tuple[str, int]], Awaitable[None]]


class CallbackGCodeHandler(GCodeHandler):
    """
    GCode handler that uses callback functions.
    
    This provides a simpler alternative to subclassing for simple use cases.
    """
    
    def __init__(
        self,
        on_received: GCodeReceivedCallback | None = None,
        on_sent: GCodeSentCallback | None = None,
    ):
        """
        Initialize with optional callback functions.
        
        Args:
            on_received: Callback for when GCode is received.
            on_sent: Callback for when GCode is sent.
        """
        self._on_received = on_received
        self._on_sent = on_sent
    
    async def on_gcode_received(self, gcode: str, client_address: tuple[str, int]) -> str:
        if self._on_received:
            return await self._on_received(gcode, client_address)
        return gcode
    
    async def on_gcode_sent(self, gcode: str, client_address: tuple[str, int]) -> None:
        if self._on_sent:
            await self._on_sent(gcode, client_address)


class CallbackResponseHandler(ResponseHandler):
    """
    Response handler that uses callback functions.
    
    This provides a simpler alternative to subclassing for simple use cases.
    """
    
    def __init__(
        self,
        on_received: ResponseReceivedCallback | None = None,
        on_sent: ResponseSentCallback | None = None,
    ):
        """
        Initialize with optional callback functions.
        
        Args:
            on_received: Callback for when a response is received.
            on_sent: Callback for when a response is sent.
        """
        self._on_received = on_received
        self._on_sent = on_sent
    
    async def on_response_received(
        self, response: str, original_gcode: str, client_address: tuple[str, int]
    ) -> str:
        if self._on_received:
            return await self._on_received(response, original_gcode, client_address)
        return response
    
    async def on_response_sent(
        self, response: str, client_address: tuple[str, int]
    ) -> None:
        if self._on_sent:
            await self._on_sent(response, client_address)
