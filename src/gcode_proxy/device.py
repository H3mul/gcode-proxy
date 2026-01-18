"""
GCode Device - Serial communication with USB devices.

This module provides the GCodeDevice class for managing serial connections
and communication with USB-connected devices using asyncio.Protocol.
"""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import serial_asyncio

from .handlers import (
    DefaultGCodeHandler,
    DefaultResponseHandler,
    GCodeHandler,
    ResponseHandler,
)
from .utils import (
    SerialConnectionError,
    clean_grbl_response,
    find_serial_port_by_usb_id,
)

if TYPE_CHECKING:
    from .task_queue import Task, TaskQueue

logger = logging.getLogger(__name__)


class GCodeDevice:
    """
    Base GCode device class that can be used for dry-run testing.

    This class provides dummy send/receive operations that log commands
    but don't actually communicate with any hardware. It consumes tasks
    from the queue and processes them.
    """

    def __init__(
        self,
        task_queue: "TaskQueue | None" = None,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 5.0,
        gcode_log_file: str | None = None,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode device.

        Args:
            task_queue: The TaskQueue to consume tasks from.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            gcode_log_file: Optional path to file for logging GCode communication.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
        """
        self.task_queue = task_queue
        self.gcode_handler = gcode_handler or DefaultGCodeHandler()
        self.response_handler = response_handler or DefaultResponseHandler()
        self.response_timeout = response_timeout
        self.gcode_log_file = Path(gcode_log_file) if gcode_log_file else None
        self.normalize_grbl_responses = normalize_grbl_responses

        self._connected = False
        self._log_lock = asyncio.Lock()
        self._task_loop_task: asyncio.Task | None = None
        self._running = False

        self.background_tasks = set()

    def run_noncritical_task(self, coro: Coroutine):
        """
        Start a coroutine that we don't want to wait for as we move on to
        next command in the queue
        """

        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        # Clean up when the task is done
        task.add_done_callback(self.background_tasks.discard)

    def set_task_queue(self, task_queue: "TaskQueue") -> None:
        """
        Set the task queue for this device.

        Args:
            task_queue: The TaskQueue to consume tasks from.
        """
        self.task_queue = task_queue

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

        # Initialize log file if specified
        if self.gcode_log_file:
            await self._initialize_log_file()

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
                        task.set_error(e)
                    finally:
                        # Mark task as done
                        self.task_queue.task_done()

                except Exception as e:
                    logger.error(f"Error in task loop: {e}")

        except asyncio.CancelledError:
            logger.info("Device task loop stopped")

    async def _process_task(self, task: "Task") -> None:
        """
        Process a single task.

        Args:
            task: The task to process.
        """
        gcode = task.command
        client_address = task.client_address

        if not gcode.endswith("\n"):
            gcode += "\n"

        try:
            await self._send(gcode)

            # Immediately listen for response, in case we miss it
            receive_task = asyncio.create_task(self._receive())

            # Notify handler that command was sent
            self.run_noncritical_task(self.gcode_handler.on_gcode(gcode, client_address))

            logger.debug(f"Sent: {gcode.strip()}")

            # Log the GCode command
            source_address = f"{client_address[0]}:{client_address[1]}"
            await self._log_gcode(task.command, source_address)

            response = await receive_task

            logger.debug(f"Received: {response.strip()}")

            # Set the response on the task
            task.set_response(response)

            # Log the response
            self.run_noncritical_task(self._log_gcode(response, "device"))

            # Notify response handler
            self.run_noncritical_task(
                self.response_handler.on_response(response, gcode, client_address)
            )

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to: {gcode.strip()}")
            task.set_response("")
        except Exception as e:
            logger.error(f"Error sending GCode: {e}")
            task.set_error(SerialConnectionError(f"Failed to send GCode: {e}"))

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

    async def _initialize_log_file(self) -> None:
        """Initialize the GCode log file."""
        if not self.gcode_log_file:
            return

        try:
            # Create parent directories if needed
            self.gcode_log_file.parent.mkdir(parents=True, exist_ok=True)

            # Create the file if it doesn't exist
            if not self.gcode_log_file.exists():
                self.gcode_log_file.touch()
                logger.info(f"Created GCode log file: {self.gcode_log_file}")
        except Exception as e:
            logger.error(f"Failed to initialize log file {self.gcode_log_file}: {e}")
            self.gcode_log_file = None

    async def _log_gcode(self, gcode: str, source: str) -> None:
        """
        Log a GCode command or response to the log file.

        Args:
            gcode: The GCode command or response to log.
            source: The source (client address or device identifier).
        """
        if not self.gcode_log_file:
            return

        try:
            # Format: [timestamp][source]: message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            log_entry = f"{timestamp} - {source}: {gcode.strip()}"

            async with self._log_lock:
                with open(self.gcode_log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")
        except Exception as e:
            logger.error(f"Failed to write to GCode log file: {e}")

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

    # Response terminators that indicate end of device response
    RESPONSE_TERMINATORS = ("ok", "error", "!!")

    def __init__(self, normalize_grbl_responses: bool = True):
        """
        Initialize the protocol.

        Args:
            normalize_grbl_responses: Whether to normalize GRBL responses.
        """
        self.transport: asyncio.Transport | None = None
        self._response_event = asyncio.Event()
        self._response_lines: list[str] = []
        self._response_complete = False
        self.normalize_grbl_responses = normalize_grbl_responses

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when the connection is established."""
        self.transport = transport  # type: ignore[assignment]
        logger.debug("Serial connection established")

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection is lost."""
        logger.debug(f"Serial connection lost: {exc}")
        self.transport = None
        # Signal any waiting coroutines
        self._response_event.set()

    def data_received(self, data: bytes) -> None:
        """
        Called when data is received from the serial device.

        Buffers data and signals when a complete response is received.

        Handles terminators (ok, error, !!) that may appear at the end of a line
        or on a separate line. Normalizes the buffer to ensure all terminators
        are on their own lines before processing.
        """

        # Decode the incoming data
        decoded_data = data.decode("utf-8", errors="replace")
        
        lines = decoded_data.split("\n")
        
        # Process complete lines
        for line in lines:
            # Normalize GRBL responses if enabled
            if self.normalize_grbl_responses:
                line = clean_grbl_response(line)
    
            logger.debug(f"Cleaned line: {line}")
            decoded_line = line.strip()

            if not decoded_line:
                continue

            # Check if line is a terminator
            if decoded_line.lower() in self.RESPONSE_TERMINATORS:
                self._response_lines.append(decoded_line)
                self._response_complete = True
                self._response_event.set()
            else:
                # Regular line, just add it
                self._response_lines.append(decoded_line)

    def write(self, data: bytes) -> None:
        """
        Write data to the serial device.

        Args:
            data: The bytes to write.
        """

        if self.transport:
            self.transport.write(data)

    def prepare_for_response(self) -> None:
        """
        Prepare to receive a response by clearing previous state.

        This must be called BEFORE sending a command to avoid race conditions
        where the device responds before wait_for_response() is called.
        """
        self._response_lines = []
        self._response_complete = False
        self._response_event.clear()

    async def wait_for_response(self, timeout: float) -> str:
        """
        Wait for a complete response from the device.

        Note: prepare_for_response() must be called before sending the command
        to avoid race conditions.

        Args:
            timeout: Timeout in seconds.

        Returns:
            The complete response string.
        """
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            if not self._response_lines:
                logger.debug("No response received within timeout")

        response = "\n".join(self._response_lines)
        self._response_lines = []
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
        task_queue: "TaskQueue | None" = None,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 5.0,
        read_buffer_size: int = 4096,
        initialization_delay: float = 0.1,
        gcode_log_file: str | None = None,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode serial device.

        Args:
            usb_id: USB device ID in vendor:product format (mutually exclusive with dev_path).
            dev_path: Device path like /dev/ttyACM0 (mutually exclusive with usb_id).
            baud_rate: Serial baud rate for communication.
            task_queue: The TaskQueue to consume tasks from.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            read_buffer_size: Size of the read buffer for serial communication.
            initialization_delay: Delay in seconds to allow device initialization after connection.
            gcode_log_file: Optional path to file for logging GCode communication.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).

        Raises:
            ValueError: If neither usb_id nor dev_path are provided
        """
        if not usb_id and not dev_path:
            raise ValueError("Must specify either usb_id or dev_path")

        super().__init__(
            task_queue=task_queue,
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            gcode_log_file=gcode_log_file,
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
            return GCodeSerialProtocol(
                normalize_grbl_responses=self.normalize_grbl_responses
            )

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

        # Initialize log file if specified
        if self.gcode_log_file:
            await self._initialize_log_file()

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
        self._protocol._response_lines = []

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
        self._protocol.prepare_for_response()
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
