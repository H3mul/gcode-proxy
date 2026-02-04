"""
GRBL Device - Serial communication with USB GRBL devices.

This module provides the GrblDevice class for managing serial connections
and communication with USB-connected GRBL devices. It uses GRBL's character
counting protocol to manage device buffer quota and handles real-time commands.
"""

import asyncio
from enum import Enum

import serial_asyncio

from gcode_proxy.core.connection_manager import ConnectionManager
from gcode_proxy.core.logging import get_logger
from gcode_proxy.core.task import GCodeTask, ShellTask, Task
from gcode_proxy.core.utils import (
    SerialConnectionError,
    is_immediate_grbl_command,
    wait_for_device,
)
from gcode_proxy.device.device import GCodeDevice
from gcode_proxy.device.grbl_device_status import GrblDeviceState, GrblDeviceStatus, HomingStatus
from gcode_proxy.device.interface import GCodeSerialProtocol
from gcode_proxy.trigger import TriggerManager

logger = get_logger()

MAX_RESPONSE_QUEUE_SIZE = 1000  # serial input lines
DEFAULT_GRBL_BUFFER_SIZE = 128  # bytes
DEFAULT_LIVENESS_PERIOD = 1000  # ms
CONFIRMATION_DELIVERY_GRACE_PERIOD = 200  # ms


class StatusBehavior(Enum):
    """Enumeration for status query behavior modes."""

    LIVENESS_CACHE = "liveness-cache"
    """
    Cache status from internal probes.
    Proxy periodically sends ? to device and caches responses.
    Client queries are served from cache.
    """

    FORWARD = "forward"
    """
    Forward status queries directly to device.
    Each client ? is sent to device, response returned to client.
    Always provides fresh device state.
    """


class GrblDevice(GCodeDevice):
    """
    GCode device that communicates with USB serial GRBL devices.

    Uses GRBL's character counting protocol to manage device buffer quota.
    Instead of lockstep request-response communication, this implementation
    sends multiple commands and monitors incoming responses to manage the
    device's limited buffer (typically 128 bytes).
    """

    def __init__(
        self,
        usb_id: str | None = None,
        dev_path: str | None = None,
        baud_rate: int = 115200,
        queue_size: int = 50,
        read_buffer_size: int = 4096,
        initialization_delay: float = 100.0,  # ms
        grbl_buffer_size: int = DEFAULT_GRBL_BUFFER_SIZE,
        liveness_period: float = DEFAULT_LIVENESS_PERIOD,  # ms
        swallow_realtime_ok: bool = True,
        device_discovery_poll_interval: float = 1000,  # ms
        status_behavior: StatusBehavior | str = StatusBehavior.FORWARD,
    ):
        """
        Initialize the GRBL serial device.

        Args:
            usb_id: USB device ID in vendor:product format (mutually exclusive with dev_path).
            dev_path: Device path like /dev/ttyACM0 (mutually exclusive with usb_id).
            baud_rate: Serial baud rate for communication.
            queue_size: Maximum number of commands allowed in the queue.
            read_buffer_size: Size of the read buffer for serial communication.
            initialization_delay: Delay in ms to allow device initialization after connection.
            grbl_buffer_size: Maximum characters allowed in device buffer (default: 128).
            liveness_period: Period in ms for pinging device with `?` command (default: 1000ms).
                Set to 0 to disable liveness probing.
            swallow_realtime_ok: Suppress 'ok' responses from `?` commands (default: True).
            device_discovery_timeout: Maximum time to wait for device to appear.
                None means wait forever (default: None).
            device_discovery_poll_interval: Time between device discovery polls
                (default: 1000 ms).
            status_behavior: How to handle status queries (StatusBehavior enum or str).
                StatusBehavior.LIVENESS_CACHE: Cache status from internal probes.
                StatusBehavior.FORWARD: Forward queries directly to device.
                (default: StatusBehavior.FORWARD)

        Raises:
            ValueError: If neither usb_id nor dev_path are provided
        """
        if not usb_id and not dev_path:
            raise ValueError("Must specify either usb_id or dev_path")

        super().__init__(
            queue_size=queue_size,
        )

        self.usb_id = usb_id
        self.dev_path = dev_path
        self.baud_rate = baud_rate
        self.read_buffer_size = read_buffer_size
        self.initialization_delay = initialization_delay / 1000
        self.grbl_buffer_size = grbl_buffer_size
        self.liveness_period = liveness_period / 1000
        self.swallow_realtime_ok = swallow_realtime_ok

        self.buffer_paused: bool = False

        # Convert string to enum if needed
        if isinstance(status_behavior, str):
            self.status_behavior = StatusBehavior(status_behavior)
        else:
            self.status_behavior = status_behavior
        self.device_discovery_poll_interval = device_discovery_poll_interval / 1000

        self._protocol: GCodeSerialProtocol | None = None
        self._response_queue: asyncio.Queue[str] = asyncio.Queue()

        # Buffer quota tracking
        self._buffer_quota = grbl_buffer_size
        self._in_flight_queue: list[Task] = []

        # Device state tracking
        self._device_state: GrblDeviceState | None = None
        self._liveness_task: asyncio.Task | None = None
        self._wait_for_device_task: asyncio.Task | None = None
        self._skippable_oks: int = 0

        # Flow control for Hold state - allows pausing/resuming task processing
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # Start in "resumed" state

        # Disconnect event for handling reconnection
        self._disconnect_event = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected to the serial device."""
        return self._connected and self._protocol is not None

    @property
    def device_state(self) -> GrblDeviceState | None:
        """Get the current device state from the latest status report."""
        return self._device_state

    async def connect(self) -> None:
        """
        Connect to the USB serial GRBL device.

        Polls for device availability until it appears or the discovery timeout is reached.
        If using usb_id, polls for devices with that ID. If using dev_path, polls for
        the device at that path.

        Raises:
            SerialConnectionError: If the connection fails.
        """
        if self._connected:
            logger.warning("Already connected to serial device")
            return

        self._wait_for_device_task = asyncio.create_task(
            wait_for_device(
                usb_id=self.usb_id,
                dev_path=self.dev_path,
                poll_interval=self.device_discovery_poll_interval,
            )
        )
        self._serial_port = await self._wait_for_device_task

        # Create the response queue for this connection
        self._response_queue = asyncio.Queue(maxsize=MAX_RESPONSE_QUEUE_SIZE)

        # Reset disconnect event for this connection
        self._disconnect_event = asyncio.Event()

        # Create the serial connection using asyncio.Protocol
        loop = asyncio.get_running_loop()

        # Create protocol factory that passes the response queue and disconnect event
        def protocol_factory():
            return GCodeSerialProtocol(
                response_queue=self._response_queue, disconnect_event=self._disconnect_event
            )

        _, self._protocol = await serial_asyncio.create_serial_connection(
            loop,
            protocol_factory,
            self._serial_port,
            baudrate=self.baud_rate,
        )

        self._device_state = GrblDeviceState()

        # Flush any startup messages from the device
        await self._flush_input()

        # Initialize device state and queues
        await self._initialize_device()

        self._connected = True
        logger.info(f"Connected to {self._serial_port} at {self.baud_rate} baud")

        # Start four concurrent tasks:
        # 1. Reconnect handler that listens for disconnects and attempts to reconnect
        # 2. Response loop that handles incoming responses
        # 3. Liveness task that pings the device periodically with `?`
        self._running = True
        self._reconnect_task = asyncio.create_task(self._handle_reconnect())
        self._response_loop_task = asyncio.create_task(self._response_loop())
        self._liveness_task = asyncio.create_task(self._liveness_task_loop())

    async def _initialize_device(self) -> None:
        """
        Initialize device state and clear all queues.

        Resets buffer quota, clears in-flight and task queues, resets state,
        and clears the ok swallowing counter. Called during device connection
        and when the device restarts (ALARM or Grbl response, or receiving 0x18 command).
        """
        logger.info("Initializing device state and queues")

        # Clear the task queue
        self.clear_queue()

        # Clear in-flight queue
        self._in_flight_queue = []

        # Clear response queue
        try:
            while not self._response_queue.empty():
                self._response_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Reset buffer management state
        self._buffer_quota = self.grbl_buffer_size
        self._skippable_oks = 0

        # Reset device state
        self._device_state = GrblDeviceState()

        # Reset resume event (allow processing to continue)
        self._resume_event.set()

        logger.debug("Device initialization complete")

    async def disconnect(self) -> None:
        """Disconnect from the serial device."""
        self._running = False

        # Cancel all task loops
        for task_ref in [
            getattr(self, "_reconnect_task", None),
            getattr(self, "_wait_for_device_task", None),
            getattr(self, "_response_loop_task", None),
            getattr(self, "_liveness_task", None),
        ]:
            if task_ref:
                task_ref.cancel()
                try:
                    await task_ref
                except asyncio.CancelledError:
                    pass

        self._reconnect_task = None
        self._wait_for_device_task = None
        self._response_loop_task = None
        self._liveness_task = None

        if self._protocol:
            try:
                self._protocol.close()
            except Exception as e:
                logger.warning(f"Error closing serial connection: {e}")
            finally:
                self._protocol = None
                self._connected = False
                logger.info("Disconnected from serial device")

    async def do_task(self, task: Task) -> None:
        """
        Process a task: check for real-time commands first, then queue if needed.

        Real-time commands are handled immediately. All other tasks are queued
        for processing by the task loop. During Alarm state, only certain commands
        ($X and $H) are allowed; others are rejected with error:9.

        Args:
            task: The task to process (GCodeTask or ShellTask).
        """

        logger.verbose(f"Received task: {repr(task)}")

        # Quick response gate: reject tasks if device is offline
        if not self._connected:
            logger.warning(f"Device offline, rejecting task: {repr(task)}")
            if task.should_respond:
                task.send_response("error: device offline")
            return

        # Check if this is a real-time command and handle it immediately
        if await self._handle_realtime_commands(task):
            return

        # Check Alarm state flow control
        if (
            self._device_state
            and self._device_state.status == GrblDeviceStatus.ALARM.value
            and not self._is_command_allowed_in_alarm(task)
        ):
            logger.warning(f"Command rejected in Alarm state: {repr(task)}")
            # Send error response if task requires one
            if task.should_respond:
                task.send_response("error:9")
            return

        # Queue non-real-time commands for processing
        await self.task_queue.put(task)

        # Kick off buffer filling if we were waiting for new tasks
        await self._fill_device_buffer()

    async def _flush_input(self) -> None:
        """Flush any pending input from the serial device."""
        if not self._protocol:
            return

        # Give a short time for any startup messages to arrive
        await asyncio.sleep(self.initialization_delay)

        # Clear any buffered data
        self._protocol.flush_input()

    async def _fill_device_buffer(self) -> None:
        """
        Fill the device buffer with tasks from the command queue.

        Respects the GRBL buffer quota: tasks are sent only if they fit within
        the available quota. Non-GCodeTask items count for 0 characters.

        Respects Hold state: if the device is in Hold state, pauses task processing
        until a resume command (~) is received or device is reinitialized.

        This method will block if the buffer is full and no responses are incoming.
        """
        while self._running and self._buffer_quota > 0 and not self.buffer_paused:
            # Check if we're in Hold state - wait for resume event if so
            if not self._resume_event.is_set():
                logger.debug("Device in Hold state, pausing task processing")
                await self._resume_event.wait()
                logger.debug("Device resumed, resuming task processing")

            try:
                # Non-blocking peek at queue
                if self.task_queue.empty():
                    break

                # Check if this is a GCodeTask and if it fits in the buffer
                if self.task_queue._queue[0].char_count > self._buffer_quota:  # pyright: ignore[reportAttributeAccessIssue]
                    logger.debug(
                        f"Device buffer too full for next task, backing off "
                        f"({self._buffer_quota * 100.0 / self.grbl_buffer_size}%)"
                    )
                    break
                # Get the next task from the queue
                task = await self.task_queue.get()

                if isinstance(task, GCodeTask):
                    # Send the GCode to the device
                    await self._send(task)

                    logger.verbose(f"Sent GCode task: {task.gcode.strip()!r}, ")

                    # Track homing operations specially
                    if self._is_homing(task) and self._device_state:
                        logger.verbose(
                            "Starting homing tracking, waiting for status to return"
                            + f" to Idle from Home; task: {repr(task)}"
                        )
                        self._device_state.homing = HomingStatus.QUEUED

                if isinstance(task, ShellTask) and task.wait_for_idle:
                    logger.verbose(
                        f"Injecting dwell before executing shell task and pausing buffer fill: "
                        f"{task.id}"
                    )
                    self.buffer_paused = True
                    dwell_task = GCodeTask(gcode="G4 P0\n", should_respond=False)
                    self._in_flight_queue.append(dwell_task)
                    await self._send(dwell_task)

                self._in_flight_queue.append(task)

                logger.verbose(f"Added task to in-flight queue: {repr(task)}")

                # Mark as done in the queue
                self.task_queue.task_done()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error filling device buffer: {e}")
                break

        # After filling buffer, drain any non-GCodeTasks
        # To make sure we are only waiting on GCode tasks in-flight
        await self._drain_non_gcode_tasks()

    async def _response_loop(self) -> None:
        """
        Loop that processes incoming response lines from the device.

        Monitors the response queue for lines from the serial device and handles them
        according to GRBL protocol. When 'ok' or 'error:' are received, the oldest
        task is completed and the buffer quota is credited back.
        """
        logger.info("Device response loop started")

        try:
            while self._running:
                try:
                    # Wait for the next serial input
                    response_line = await self._response_queue.get()
                    await self._handle_response_line(response_line)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error in response loop: {e}")

        except asyncio.CancelledError:
            logger.info("Device response loop stopped")

    async def _liveness_task_loop(self) -> None:
        """
        Loop that pings the device periodically with `?` command.

        Sends a `?` command every liveness_period ms to request
        a status report from the device. This helps maintain the device state
        and ensures the connection is still active.

        If liveness_period is 0, this task is disabled and returns immediately.
        """
        # Check if liveness probing is disabled
        if self.liveness_period == 0:
            logger.info("Device liveness task disabled (liveness_period is 0)")
            return

        logger.info(f"Device liveness task started (period: {self.liveness_period * 1000}ms)")

        try:
            while self._running:
                try:
                    # Wait for the next liveness period
                    await asyncio.sleep(self.liveness_period)

                    # Send the status request command
                    if self._protocol:
                        await self._send(GCodeTask(gcode="?", should_respond=False))
                        # Increment counter for skippable ok if configured
                        if self.swallow_realtime_ok:
                            self._skippable_oks += 1
                        logger.verbose(
                            f"Sent status request (?), skippable_oks: {self._skippable_oks}"
                        )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error in liveness task: {e}")
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("Device liveness task stopped")

    async def _handle_reconnect(self) -> None:
        """
        Monitor for disconnect events and automatically attempt reconnection.

        This task continuously waits for the disconnect event. When the device
        disconnects, it cleans up the current connection and attempts to reconnect
        by polling for the device to come back online.
        """
        try:
            while self._running:
                # Wait for disconnect event
                await self._disconnect_event.wait()

                if not self._running:
                    break

                logger.info("Device disconnected, attempting to reconnect...")

                # Clean up current connection
                try:
                    await self.disconnect()
                except Exception as e:
                    logger.error(f"Error during disconnect cleanup: {e}")

                # Attempt to reconnect
                try:
                    await self.connect()
                    logger.info("Device reconnected successfully")
                except Exception as e:
                    logger.error(f"Failed to reconnect to device: {e}")
                    # Wait a bit before attempting again
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.debug("Reconnect handler stopped")

    async def _handle_response_line(self, line: str) -> None:
        """
        Handle a single response line from the device.

        Routes the line to appropriate handlers based on its format.

        Args:
            line: A single cleaned response line from the device.
        """
        logger.verbose(f"Processing response line: {line!r}")

        if line.startswith("ok"):
            await self._handle_ok_response(line)

        elif line.startswith("error:"):
            await self._handle_task_completion(line, success=False)

        elif line.startswith("ALARM:"):
            logger.warning(f"Received device alarm: {line}")
            # Set device state preemptively to Alarm
            if self._device_state:
                self._device_state.status = GrblDeviceStatus.ALARM
                logger.verbose(f"Device state updated preemptively to: {self._device_state.status}")
            await self._broadcast_data_to_clients(line)
            await self._initialize_device()

        elif line.startswith("<"):
            if self.status_behavior == StatusBehavior.FORWARD:
                await self._respond_to_client(line)
            await self._handle_state_update(line)

        elif line.startswith("["):
            await self._broadcast_data_to_clients(line)

        elif line.startswith("$"):
            await self._respond_to_client(line)

        elif "Grbl " in line:
            logger.info(f"Device initialization message: {line}")
            await self._broadcast_data_to_clients(line)
            await self._initialize_device()

        else:
            logger.debug(f"Unhandled device response: {line}")

    async def _handle_ok_response(self, line: str) -> None:
        """
        Handle an 'ok' response from the device.

        Checks if this is a status request 'ok' to be swallowed, or a
        real command completion. Only processes task completion if not swallowed.

        Args:
            line: The 'ok' response line from the device.
        """
        if self._should_swallow_ok():
            return

        await self._handle_task_completion(line, success=True)

    async def _handle_realtime_commands(self, task: Task) -> bool:
        """
        Handle real-time commands immediately without queuing.

        Real-time commands in GRBL are processed immediately and bypass the
        character counting protocol. This method checks if a task contains a
        real-time command and handles it accordingly.

        Real-time commands handled:
        - 0x18 (Ctrl+X): Soft reset - reinitialize device
        - '?': Status query - serve cached state, no device send
        - '!': Feed hold - updates state to Hold preemptively
        - '~': Cycle start/resume - updates state to Run and resumes processing

        Args:
            task: The task to check for real-time commands.

        Returns:
            True if the task was handled as a real-time command, False otherwise.
        """
        # Check if this is a GCodeTask
        if not isinstance(task, GCodeTask):
            return False

        gcode = task.gcode.strip()

        # Handle soft reset (0x18 or Ctrl+X)
        if gcode == "\x18" or gcode == "0x18":
            logger.info("Real-time command: Soft reset (0x18)")
            await self._initialize_device()

        # Handle status query (?)
        elif gcode == "?":
            logger.verbose("Real-time command: Status query (?)")

            if self.status_behavior == StatusBehavior.FORWARD:
                # Forward mode: send query to device and track as in-flight
                logger.verbose("Status query forwarded to device (forward mode)")
                # Push as oldest in-flight command to be responded to next
                self._in_flight_queue.insert(0, task)
                await self._send(GCodeTask(gcode=gcode))
            else:
                # liveness-cache mode: serve from cached state
                if self._device_state and self._device_state.status_line:
                    # Send the cached status report to the client
                    status_report = self._device_state.status_line
                    if task.should_respond:
                        task.send_response(status_report + "\nok\n")
                        logger.verbose(f"Sent cached status report to client: {status_report}")
            return True

        # Handle feed hold (!)
        elif gcode == "!":
            logger.debug("Real-time command: Feed hold (!)")
            # Update device state preemptively to Hold
            if self._device_state:
                self._device_state.status = GrblDeviceStatus.HOLD
                logger.verbose(f"Device state updated preemptively to: {self._device_state.status}")
            # Pause task processing by clearing the resume event
            self._resume_event.clear()

        # Handle cycle start/resume (~)
        elif gcode == "~":
            logger.debug("Real-time command: Cycle start/resume (~)")
            # Update device state preemptively to Run
            if self._device_state:
                self._device_state.status = GrblDeviceStatus.RUN
                logger.verbose(f"Device state updated preemptively to: {self._device_state.status}")
            # Resume task processing by setting the resume event
            self._resume_event.set()

        else:
            return False

        await self._send(GCodeTask(gcode=gcode))
        return True

    async def _handle_state_update(self, line: str) -> None:
        """
        Handle a status report (device state update).

        Parses the status report and updates internal device state,
        then broadcasts the report to all connected clients.

        Args:
            line: The status report line from the device.
        """

        if not self._device_state:
            self._device_state = GrblDeviceState()

        old_status = self._device_state.status
        self._device_state.update_status(line)

        # Handle state changes
        if self._device_state.status != old_status:
            logger.debug(f"Device changed state from {old_status} to {self._device_state.status}")

            # Trigger state-based triggers asynchronously
            asyncio.create_task(TriggerManager().on_device_status(self._device_state.status))

            # Redundancy check for ALARM state to reinitialize (in case we missed ALARM: message)
            if self.device_state == GrblDeviceStatus.ALARM.value:
                logger.warning("Device state changed to Alarm, reinitializing device")
                await self._initialize_device()

            # We finished homing, but the homing "ok" hasn't arrived yet
            if (
                self._device_state.homing == HomingStatus.QUEUED
                and old_status == GrblDeviceStatus.HOME.value
                and self._device_state.status == GrblDeviceStatus.IDLE.value
            ):
                logger.verbose("Detected homing task end via state update")
                self._device_state.homing = HomingStatus.COMPLETE

                # Allow some time for the ok to arrive,
                # then complete the homing task when we're sure it won't
                async def complete_homing_task():
                    await asyncio.sleep(CONFIRMATION_DELIVERY_GRACE_PERIOD / 1000)
                    if (
                        self._is_homing_in_flight()
                        and self._device_state
                        and self._device_state.homing == HomingStatus.COMPLETE
                    ):
                        logger.info("Homing 'ok' lost, completing homing task based on Idle")
                        await self._handle_task_completion("ok", success=True)

                asyncio.create_task(complete_homing_task())

    async def _handle_task_completion(self, response_line: str, success: bool) -> None:
        """
        Handle completion of a task based on device response.

        When a task completes (ok or error), this method:
        1. Pops the oldest in-flight task
        2. Credits back the character count (if GCodeTask)
        3. Sends response to the client
        4. Drains any non-GCodeTasks following it and executes them
        5. Attempts to fill the buffer with more tasks

        Args:
            response_line: The response line from the device (ok, error:, etc.)
            success: Whether the response indicates success.
        """
        if not self._in_flight_queue:
            logger.warning(f"Received response but no in-flight tasks: {response_line}")
            return

        # Pop the oldest in-flight task
        completed_task = self._in_flight_queue.pop(0)
        logger.verbose(f"Completed task: {repr(completed_task)}")

        # Credit back the buffer quota if it's a GCodeTask
        if isinstance(completed_task, GCodeTask):

            if not is_immediate_grbl_command(completed_task.gcode):
                self._buffer_quota += completed_task.char_count
                logger.verbose(
                    f"Credited {completed_task.char_count} chars,"
                    f"for task {repr(completed_task.gcode)} "
                    f"buffer quota now: {self._buffer_quota} "
                    f"({self._buffer_quota * 100.0 / self.grbl_buffer_size}%)"
                )

            # Make sure we finish homing tracking in case we got an ok before state change
            if self._is_homing(completed_task) and self._device_state:
                logger.verbose(
                    f"Completing homing tracking: ok received (task: {repr(completed_task)})"
                )
                self._device_state.homing = HomingStatus.OFF

        # Send response to the completed task's client
        if completed_task.should_respond:
            completed_task.send_response(response_line)

        # Drain any non-GCodeTasks following this task and execute them
        await self._drain_non_gcode_tasks()

        # Try to fill buffer with more tasks
        await self._fill_device_buffer()

    async def _drain_non_gcode_tasks(self) -> None:
        """
        Drain and execute all non-GCodeTasks from the in-flight queue.

        This is used during device reinitialization to ensure that any
        pending shell tasks are executed after the device resets.
        """

        while self._in_flight_queue and not isinstance(self._in_flight_queue[0], GCodeTask):
            shell_task = self._in_flight_queue.pop(0)

            if isinstance(shell_task, ShellTask):
                if shell_task.wait_for_idle:
                    # Resume buffer filling, this task caused it to pause
                    self.buffer_paused = False

                logger.verbose(f"Executing shell task during drain: {shell_task.id}")
                response = ""
                try:
                    success_val, error_msg = await shell_task.execute()
                    response = "ok" if success_val else f"error: {error_msg}"
                except Exception as e:
                    logger.error(f"Error executing shell task {shell_task.id}: {e}")
                    response = f"error: {e}"
                finally:
                    if shell_task.should_respond:
                        shell_task.send_response(response)

                    logger.verbose(f"Completed task: {repr(shell_task)}")

    def _should_swallow_ok(self) -> bool:
        """
        Check if this 'ok' response should be swallowed.

        Returns:
            True if this is a status request 'ok' to be discarded, False otherwise.
        """
        if not self.swallow_realtime_ok or self._skippable_oks == 0:
            return False

        self._skippable_oks -= 1
        logger.verbose(f"Swallowed ok from status request, remaining: {self._skippable_oks}")
        return True

    def _is_homing_in_flight(self) -> bool:
        """
        Check if we're still waiting to finish a homing command
        """

        task = self._get_oldest_gcode_task()
        return self._is_homing(task)

    def _is_homing(self, task: GCodeTask | None) -> bool:
        """
        Check if the given task is a homing command ($H)
        """

        return bool(task and task.gcode.strip().upper() == "$H")

    def _is_command_allowed_in_alarm(self, task: Task) -> bool:
        """
        Check if a command is allowed to be queued/executed during Alarm state.

        In Alarm state, only specific commands are allowed:
        - $X: Kill alarm lock
        - $H: Home the machine

        Args:
            task: The task to check.

        Returns:
            True if the command is allowed in Alarm state, False otherwise.
        """
        if not isinstance(task, GCodeTask):
            return True

        gcode = task.gcode.strip().upper()
        # Only allow $X (kill alarm) and $H (home) in Alarm state
        return gcode == "$X" or gcode == "$H"

    def _get_oldest_gcode_task(self) -> GCodeTask | None:
        """
        Get the oldest in-flight GCode task without removing it.

        Returns:
            The oldest GCodeTask in the in-flight queue, or None if:
            - The queue is empty
            - The oldest task is not a GCodeTask
        """
        if self._in_flight_queue and isinstance(self._in_flight_queue[0], GCodeTask):
            return self._in_flight_queue[0]
        return None

    async def _respond_to_client(self, line: str) -> None:
        """
        Send data back to the currently executing task client

        Args:
            line: The data line to send to the client.
        """

        task = self._get_oldest_gcode_task()
        if task and task.should_respond:
            logger.verbose(f"Sent data to client of task: {repr(task)}, data: {line}")
            task.send_response(line)

    async def _broadcast_data_to_clients(self, line: str) -> None:
        """
        Broadcast data back to all currently executing task clients

        Args:
            line: The data line to broadcast to clients.
        """

        ConnectionManager().broadcast(line)

    async def _send(self, task: GCodeTask) -> None:
        """
        Send a GCode command to the serial device.

        Args:
            gcode: The GCode command to send (already has newline appended).

        Raises:
            SerialConnectionError: If the protocol is not available.
        """
        if not self._protocol:
            msg = "Serial protocol is not available"
            raise SerialConnectionError(msg)

        self._protocol.write(task.gcode)

        if not is_immediate_grbl_command(task.gcode):
            # Deduct from quota and add to in-flight
            self._buffer_quota -= task.char_count
            logger.verbose(
                f"Buffer quota deducted after sending task: {self._buffer_quota}"
                f"({self._buffer_quota * 100.0 / self.grbl_buffer_size}%), task: {repr(task.gcode)}"
            )
