"""
GCode Device - Serial communication with USB devices.

This module provides the GCodeDevice class for managing serial connections
and communication with USB-connected devices using asyncio.Protocol.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import TYPE_CHECKING

import serial_asyncio

from gcode_proxy.logging import get_gcode_logger, log_gcode

from .handlers import (
    DefaultGCodeHandler,
    DefaultResponseHandler,
    GCodeHandler,
    ResponseHandler,
)
from .utils import (
    SerialConnectionError,
    clean_grbl_response,
    detect_grbl_terminator,
    detect_grbl_soft_reset_command,
    find_serial_port_by_usb_id,
)

from .task_queue import create_task_queue, empty_queue

if TYPE_CHECKING:
    from .task_queue import Task

logger = logging.getLogger(__name__)
gcode_logger = get_gcode_logger()


class GCodeDevice:
    """
    Base GCode device class that can be used for dry-run testing.

    This class provides dummy send/receive operations that log commands
    but don't actually communicate with any hardware. It consumes tasks
    from the queue and processes them.
    """

    def __init__(
        self,
        queue_size: int = 50,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 30.0,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode device.

        Args:
            queue_size: Maximum number of commands allowed in the queue.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
        """
        self.task_queue = create_task_queue(maxsize=queue_size)
        self.gcode_handler = gcode_handler or DefaultGCodeHandler()
        self.response_handler = response_handler or DefaultResponseHandler()
        self.response_timeout = response_timeout
        self.normalize_grbl_responses = normalize_grbl_responses

        self._connected = False
        self._task_loop_task: asyncio.Task | None = None
        self._running = False

    async def handle_soft_reset(self, gcode: str) -> None:
        if not detect_grbl_soft_reset_command(gcode):
            return

        logging.info("Soft reset received, clearing command queue")

        self.clear_queue()

    async def do_task(self, task: "Task") -> None:
        """
        Process a task: queue it if needed or process it immediately

        Args:
            task: The task to process.
        """

        logger.verbose(f"Received task: {repr(task)}")

        if task.queue_task:
            await self.task_queue.put(task)
        else:
            await self._process_task(task)

    async def execute_task_now(self, task: "Task") -> None:
        """
        Execute a task immediately, bypassing the queue.

        Args:
            task: The task to execute.
        """
        await self._process_task(task)

    def clear_queue(self) -> None:
        """Clear all pending tasks from the queue."""
        empty_queue(self.task_queue)

    def queue_size(self) -> int:
        """Get the current size of the task queue."""
        return self.task_queue.qsize()

    def queue_full(self) -> bool:
        """Check if the task queue is full."""
        return self.task_queue.full()

    def queue_maxsize(self) -> int:
        """Get the maximum size of the task queue."""
        return self.task_queue.maxsize

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected."""
        return self._connected

    async def connect(self) -> None:
        """
        Connect to the device.

        For the base class (dry-run mode), this simply marks the device as connected
        and starts the task processing loop.
        """
        if self._connected:
            logger.warning("Already connected to device")
            return

        self._connected = True
        logger.info("Connected to dry-run device (no actual hardware)")

        # Start the task processing loop
        self._running = True
        self._task_loop_task = asyncio.create_task(self._task_loop())

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        self._running = False

        # Cancel the task loop
        if self._task_loop_task:
            self._task_loop_task.cancel()
            try:
                await self._task_loop_task
            except asyncio.CancelledError:
                pass
            self._task_loop_task = None

        if self._connected:
            self._connected = False
            logger.info("Disconnected from dry-run device")

    async def _task_loop(self) -> None:
        """
        Main loop that processes tasks from the queue.

        Continuously awaits tasks from the queue and processes them.
        """
        if not self.task_queue:
            logger.error("No task queue set for device")
            return

        logger.info("Device task loop started")

        try:
            while self._running:
                try:
                    # Wait for a task from the queue
                    task = await self.task_queue.get()

                    try:
                        # Process the task
                        await self._process_task(task)
                    except Exception as e:
                        logger.error(f"Error processing task: {e}")
                        task.send_response(f"error: {e}")
                    finally:
                        # Mark task as done
                        self.task_queue.task_done()

                except Exception as e:
                    logger.error(f"Error in task loop: {e}")

        except asyncio.CancelledError:
            logger.info("Device task loop stopped")

    async def _synchronize_device(self) -> str:
        """
        Inject a synchronization command to force device buffer completion.

        Sends a G4 P0 (dwell with 0 duration) command to the device and waits
        for the response. This forces all prior commands in the device buffer
        to complete before returning.

        Returns:
            The device response to the synchronization command.

        Raises:
            asyncio.TimeoutError: If the device doesn't respond in time.
            SerialConnectionError: If the serial connection is not available.
        """

        sync_command = "G4 P0\n"

        try:
            logger.debug(f"Injecting synchronization command: {sync_command.strip()}")
            log_gcode(sync_command, "server", "injected synchronization")

            await self._send(sync_command)
            sync_response = await self._receive()

            logger.debug(f"Synchronization response: {sync_response.strip()}")
            logger.info("Device task execution synchronized")
            return sync_response

        except asyncio.TimeoutError:
            logger.warning("Timeout during device synchronization")
            raise
        except Exception as e:
            logger.error(f"Error during device synchronization: {e}")
            raise

    async def _process_task(self, task: "Task") -> None:
        """
        Process a single task.

        Calls the GCode handler (pre-phase) to match triggers and execute those
        that don't require synchronization. If synchronization is needed, injects
        G4 P0 command and then calls the handler (post-phase) to execute deferred
        triggers. Multiple triggers can match with different behaviors:
        - If ANY trigger is FORWARD, GCode is sent to device
        - If ALL triggers are CAPTURE, GCode is not sent to device
        - Responses are merged based on trigger execution results
        - If ANY trigger has synchronize flag, a G4 P0 is injected before execution

        Args:
            task: The task to process.
        """
        gcode = task.command

        from .connection_manager import ConnectionManager
        client_address = ConnectionManager().get_client_address(task.client_uuid) or ("unknown", 0)
        source_address = f"{client_address[0]}:{client_address[1]}"

        if not gcode.endswith("\n"):
            gcode += "\n"

        try:
            await self.handle_soft_reset(gcode)

            # Pre-phase: Call the GCode handler and get behavior config
            handler_result = await self.gcode_handler.on_gcode_pre(gcode, client_address)

            should_forward = getattr(handler_result, "should_forward", True)
            fake_response = getattr(handler_result, "fake_response", None)
            should_synchronize = getattr(handler_result, "should_synchronize", False)

            # If synchronization is needed, inject G4 P0 before proceeding
            if should_synchronize:
                await self._synchronize_device()
                post_result = await self.gcode_handler.on_gcode_post(gcode, client_address)

                if post_result:
                    # Merge pre and post responses
                    if fake_response == "ok" and post_result != "ok":
                        fake_response = post_result
                    else:
                        fake_response = f"{fake_response} {post_result}"

            if not should_forward:
                # All triggers captured the command, don't send to device
                response = fake_response or "ok"
                logger.debug(f"All triggers captured command, returning: {response}")
                log_gcode(task.command, source_address, "not forwarded to device")
                log_gcode(response, "trigger", "response")
            else:
                log_gcode(task.command, source_address, "forwarded to device")

                # Send to device
                await self._send(gcode)
                logger.debug(f"Sent: {repr(gcode.strip())}")

                if task.wait_response:
                    device_response = await self._receive()
                    logger.debug(f"Received: {device_response.strip()}")
                    log_gcode(device_response, "device", "device clean response")
                    response = device_response
                else:
                    response = "ok"

            # Set the response on the task
            task.send_response(response)

            # Log the response

            # Notify response handler and wait for it to complete
            if task.wait_response:
                await self.response_handler.on_response(response, gcode, client_address)

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to: {gcode.strip()}")
            message = "server-error: timed out waiting for server response"
            log_gcode(message, "server", "command timeout")
            task.send_response(message)
        except Exception as e:
            logger.error(f"Error sending GCode: {e}")
            task.send_response("error: failed to send GCode")

    async def _send(self, gcode: str) -> None:
        """
        Send a GCode command to the device.

        Override this method in subclasses for actual hardware communication.

        Args:
            gcode: The GCode command to send (already has newline appended).
        """
        logger.debug(f"[DRY-RUN] Would send: {gcode.strip()}")

    async def _receive(self) -> str:
        """
        Receive a response from the device.

        Override this method in subclasses for actual hardware communication.

        Returns:
            The response string from the device.
        """
        logger.debug("[DRY-RUN] Returning simulated 'ok' response")
        return "ok"

    async def __aenter__(self) -> "GCodeDevice":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()


class GCodeSerialProtocol(asyncio.Protocol):
    """
    asyncio.Protocol implementation for serial communication with GCode devices.

    This protocol handles the low-level serial communication and buffers
    incoming data until complete responses are received.
    """

    def __init__(self, normalize_grbl_responses: bool = True):
        """
        Initialize the protocol.

        Args:
            normalize_grbl_responses: Whether to normalize GRBL responses.
        """
        self.transport: asyncio.Transport | None = None
        self._response = asyncio.Future()
        self._buffer: str = ""
        self.normalize_grbl_responses = normalize_grbl_responses

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when the connection is established."""
        self.transport = transport  # type: ignore[assignment]
        logger.debug("Serial connection established")

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection is lost."""
        logger.debug(f"Serial connection lost: {exc}")
        self.transport = None

        if self._response and not self._response.done():
            self._response.set_result("error: device disconnected")

    def data_received(self, data: bytes) -> None:
        """
        Called when data is received from the serial device.

        Buffers data and signals when a complete response is received.

        Handles terminators (ok, error, !!) that may appear at the end of a line
        or on a separate line. Normalizes the buffer to ensure all terminators
        are on their own lines before processing.
        """

        logger.verbose(f"Raw serial data received: {repr(data)}")  # type: ignore[attr-defined]
        log_gcode(data, "device", "serial data in")

        # Operate on the cumulative buffer for current command response
        # In case serial data gets split across multiple flush chunks
        self._buffer += data.decode("utf-8", errors="replace")
        lines = self._buffer.split("\n")

        _response_lines = []

        # Process complete lines
        for line in lines:
            # Normalize GRBL responses if enabled
            if self.normalize_grbl_responses:
                line = clean_grbl_response(line)

            decoded_line = line.strip()

            if not decoded_line:
                continue

            _response_lines.append(decoded_line)

            # Check if line is a terminator
            if detect_grbl_terminator(decoded_line.lower()):
                if self._response and not self._response.done():
                    self._response.set_result(_response_lines)
                self.flush_input()

    def flush_input(self) -> None:
        """Flush any buffered input data."""
        self._buffer = ""

    def write(self, data: bytes) -> None:
        """
        Write data to the serial device.

        Args:
            data: The bytes to write.
        """

        if self.transport:
            self.transport.write(data)

    async def wait_for_response(self, timeout: float) -> str:
        """
        Wait for a complete response from the device.

        Args:
            timeout: Timeout in seconds.

        Returns:
            The complete response string.
        """

        self._response = asyncio.Future()
        response_lines = await asyncio.wait_for(self._response, timeout=timeout)
        response = "\n".join(response_lines)
        return response

class GCodeSerialDevice(GCodeDevice):
    """
    GCode device that communicates with USB serial devices.

    This class extends GCodeDevice with actual serial communication
    capabilities using asyncio.Protocol.
    """

    def __init__(
        self,
        usb_id: str | None = None,
        dev_path: str | None = None,
        baud_rate: int = 115200,
        queue_size: int = 50,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 30.0,
        read_buffer_size: int = 4096,
        initialization_delay: float = 0.1,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode serial device.

        Args:
            usb_id: USB device ID in vendor:product format (mutually exclusive with dev_path).
            dev_path: Device path like /dev/ttyACM0 (mutually exclusive with usb_id).
            baud_rate: Serial baud rate for communication.
            queue_size: Maximum number of commands allowed in the queue.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            read_buffer_size: Size of the read buffer for serial communication.
            initialization_delay: Delay in seconds to allow device initialization after connection.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).

        Raises:
            ValueError: If neither usb_id nor dev_path are provided
        """
        if not usb_id and not dev_path:
            raise ValueError("Must specify either usb_id or dev_path")

        super().__init__(
            queue_size=queue_size,
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
        )

        self.usb_id = usb_id
        self.dev_path = dev_path
        self.baud_rate = baud_rate
        self.response_timeout = response_timeout
        self.read_buffer_size = read_buffer_size
        self.initialization_delay = initialization_delay
        self.normalize_grbl_responses = normalize_grbl_responses

        self._transport: asyncio.Transport | None = None
        self._protocol: GCodeSerialProtocol | None = None

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected to the serial device."""
        return self._connected and self._protocol is not None

    async def connect(self) -> None:
        """
        Connect to the USB serial device.

        Raises:
            SerialDeviceNotFoundError: If the device cannot be found (when using usb_id).
            SerialConnectionError: If the connection fails.
        """
        if self._connected:
            logger.warning("Already connected to serial device")
            return

        # Determine the serial port to use
        if self.dev_path:
            if self.usb_id:
                logger.warning("Both usb_id and dev_path are specified; using dev_path")
            self._serial_port = self.dev_path
        else:
            # Find the serial port for the USB device
            assert self.usb_id is not None
            self._serial_port = find_serial_port_by_usb_id(self.usb_id)

        # Create the serial connection using asyncio.Protocol
        loop = asyncio.get_running_loop()

        # Create protocol factory that passes the normalize flag
        def protocol_factory():
            return GCodeSerialProtocol(normalize_grbl_responses=self.normalize_grbl_responses)

        self._transport, self._protocol = await serial_asyncio.create_serial_connection(
            loop,
            protocol_factory,
            self._serial_port,
            baudrate=self.baud_rate,
        )

        self._connected = True
        logger.info(f"Connected to {self._serial_port} at {self.baud_rate} baud")

        # Give the device a moment to initialize
        await asyncio.sleep(self.initialization_delay)

        # Flush any startup messages from the device
        await self._flush_input()

        # Start the task processing loop
        self._running = True
        self._task_loop_task = asyncio.create_task(self._task_loop())

    async def disconnect(self) -> None:
        """Disconnect from the serial device."""
        self._running = False

        # Cancel the task loop
        if self._task_loop_task:
            self._task_loop_task.cancel()
            try:
                await self._task_loop_task
            except asyncio.CancelledError:
                pass
            self._task_loop_task = None

        if self._transport:
            try:
                self._transport.close()
            except Exception as e:
                logger.warning(f"Error closing serial connection: {e}")
            finally:
                self._transport = None
                self._protocol = None
                self._connected = False
                logger.info("Disconnected from serial device")

    async def _flush_input(self) -> None:
        """Flush any pending input from the serial device."""
        if not self._protocol:
            return

        # Give a short time for any startup messages to arrive
        await asyncio.sleep(self.initialization_delay)

        # Clear any buffered data
        self._protocol.flush_input()

    async def _send(self, gcode: str) -> None:
        """
        Send a GCode command to the serial device.

        Args:
            gcode: The GCode command to send (already has newline appended).

        Raises:
            SerialConnectionError: If the protocol is not available.
        """
        if not self._protocol:
            raise SerialConnectionError("Serial protocol is not available")

        # Prepare to receive response BEFORE sending to avoid race conditions
        self._protocol.write(gcode.encode("utf-8"))

    async def _receive(self) -> str:
        """
        Read a response from the serial device.

        Uses the protocol's wait_for_response method to wait for a complete response.

        Returns:
            The complete response string.
        """
        if not self._protocol:
            return ""

        return await self._protocol.wait_for_response(self.response_timeout)
