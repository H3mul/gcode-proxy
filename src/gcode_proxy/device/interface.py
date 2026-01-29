"""
Serial Protocol Interface - ASCII-based serial communication with GRBL devices.

This module provides the GCodeSerialProtocol class for handling low-level
serial communication with GRBL-compatible devices using asyncio.
"""

import asyncio
from typing import TYPE_CHECKING, Optional, cast

from gcode_proxy.core.utils import clean_grbl_response
from gcode_proxy.core.logging import log_gcode_recv, log_gcode_sent, get_logger

if TYPE_CHECKING:
    from asyncio import Queue, Event

logger = get_logger()

class GCodeSerialProtocol(asyncio.Protocol):
    """
    asyncio.Protocol implementation for serial communication with GRBL devices.

    This protocol handles low-level serial communication, ASCII encoding/decoding,
    and line-by-line buffering of incoming data. All responses are normalized
    to standard GRBL format and pushed to a queue for processing.
    """

    def __init__(
        self,
        response_queue: "Queue[str]",
        transport: "asyncio.Transport | None" = None,
        disconnect_event: "Event | None" = None
    ):
        """
        Initialize the protocol.

        Args:
            response_queue: An asyncio Queue to receive parsed response lines.
            disconnect_event: An optional asyncio Event that will be set when
                the connection is lost.
        """
        self.response_queue = response_queue
        self.disconnect_event = disconnect_event
        self._input_buffer: str = ""
        self.transport = None

    def connection_made(self, transport) -> None:
        """Called when the connection is established."""
        self.transport = cast(asyncio.Transport, transport)
        logger.debug("Serial connection established")

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection is lost."""
        logger.debug(f"Serial connection lost: {exc}")
        self.transport = None

        # Signal disconnect event if provided
        if self.disconnect_event:
            self.disconnect_event.set()

    def data_received(self, data: bytes) -> None:
        """
        Called when data is received from the serial device.

        Decodes data as ASCII (handling decode errors by logging as potential garbage),
        buffers it character by character, and pushes complete lines to the response queue
        when newlines are encountered.

        Args:
            data: Raw bytes received from the serial device.
        """
        try:
            decoded_data = data.decode("ascii")
        except UnicodeDecodeError as e:
            logger.warning(f"Failed to decode serial data as ASCII (potential garbage): {e}")
            return

        logger.verbose(f"Raw serial data received: {repr(data)}")

        # Process character by character, accumulating in buffer
        for char in decoded_data:
            if char == "\n":
                # Line complete - process and push to queue
                line = self._input_buffer.strip()
                self._input_buffer = ""

                if line:
                    # Normalize GRBL response (always enabled)
                    cleaned_line = clean_grbl_response(line)
                    cleaned_line = cleaned_line.strip()

                    if cleaned_line:
                        self.response_queue.put_nowait(cleaned_line)
                        log_gcode_recv(cleaned_line)
            else:
                # Accumulate character in buffer
                self._input_buffer += char

    def write(self, data: str) -> None:
        """
        Write data to the serial device.

        Encodes the string as ASCII before sending. Raises an exception on encoding errors.

        Args:
            data: The string to write.

        Raises:
            UnicodeEncodeError: If the string cannot be encoded as ASCII.
        """
        if not self.transport:
            logger.warning("Cannot write data - transport not available")
            return

        try:
            encoded_data = data.encode("ascii")
            if self.transport:
                self.transport.write(encoded_data)
            log_gcode_sent(data.strip())
            logger.verbose(f"Raw serial data sent: {repr(encoded_data)}")
        except UnicodeEncodeError as e:
            logger.error(f"Failed to encode GCode as ASCII: {e}")
            raise

    def flush_input(self) -> None:
        """Flush any buffered input data."""
        self._input_buffer = ""

    def close(self) -> None:
        """Close the serial connection."""
        if self.transport:
            self.transport.close()
            logger.debug("Serial connection closed")
