"""
Extensible handlers for GCode and serial response processing.

These handlers provide hooks for custom processing of incoming GCode commands
and serial responses. Future implementations can extend these to trigger
external scripts or perform custom actions based on the data.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
from typing import Any


@dataclass
class GCodeHandlerPreResponse:
    """
    Response data from on_gcode_pre handler.
    
    Attributes:
        should_forward: Whether to send GCode to device.
        fake_response: Response for CAPTURE modes, or None.
        should_synchronize: Whether sync is needed.
    """
    should_forward: bool
    fake_response: str | None
    should_synchronize: bool
    
class GCodeHandler(ABC):
    """
    Abstract base class for handling incoming GCode commands.
    
    Extend this class to implement custom processing of GCode commands
    before they are forwarded to the serial device.
    """
    
    @abstractmethod
    async def on_gcode_pre(
        self, gcode: str, client_address: tuple[str, int]
    ) -> GCodeHandlerPreResponse | None:
        """
        Called when a GCode command is received before being sent to the device.
        
        This is the pre-phase handler. For handlers supporting two-stage trigger
        execution, this should execute non-synchronizing triggers and return
        behavior metadata. For backwards compatibility, this may also execute
        all triggers.
        
        Args:
            gcode: The GCode command that was received.
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            Optional GCodeHandlerPreResponse with behavior metadata:
            - should_forward: Whether to send GCode to device
            - fake_response: Response for CAPTURE modes
            - should_synchronize: Whether sync is needed
            
            Returns None if no special handling is needed (default behavior).
        """
        pass

    async def on_gcode_post(
        self, gcode: str, client_address: tuple[str, int]
    ) -> str | None:
        """
        Called for post-synchronization trigger handling (optional).
        
        This is called after device synchronization (G4 P0) is complete.
        Handlers that support deferred trigger execution implement this.
        
        Args:
            gcode: The GCode command (for reference).
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            result to send back to the client
        """
        return None


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
    
    async def on_gcode_pre(
        self, gcode: str, client_address: tuple[str, int]
    ) -> GCodeHandlerPreResponse | None:
        """No-op, return None for default behavior."""
        return None


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
GCodeCallback = Callable[[str, tuple[str, int]], Awaitable[dict[str, Any] | None]]
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
    
    async def on_gcode_pre(
        self, gcode: str, client_address: tuple[str, int]
    ) -> GCodeHandlerPreResponse | None:
        if self._on_gcode:
            return await self._on_gcode(gcode, client_address)
        return None


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
