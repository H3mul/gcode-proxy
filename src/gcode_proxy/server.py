"""
TCP Server for GCode Proxy.

This module provides the async TCP server that accepts client connections
and forwards GCode commands to the task queue for processing by the device.
"""

import asyncio
from collections.abc import Coroutine
import logging

from gcode_proxy.utils import is_immediate_grbl_command
from .device import GCodeDevice
from .task_queue import Task
from .connection_manager import ConnectionManager
from gcode_proxy.logging import log_gcode

logger = logging.getLogger(__name__)


class GCodeServer:
    """
    Async TCP server for receiving GCode commands from clients.

    This server accepts TCP connections, reads GCode commands,
    creates tasks and adds them to the queue for processing by the device.
    """

    def __init__(
        self,
        device: GCodeDevice,
        address: str = "0.0.0.0",
        port: int = 8080,
        response_timeout: float = 30.0,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode server.

        Args:
            device: The GCodeDevice instance.
            address: The address to bind the server to.
            port: The port to listen on.
            response_timeout: Timeout in seconds for waiting for device response.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
        """
        self.device = device
        self.address = address
        self.port = port
        self.response_timeout = response_timeout
        self.normalize_grbl_responses = normalize_grbl_responses

        self._server: asyncio.Server | None = None
        self._running = False
        self._active_connections: set[asyncio.Task] = set()
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        """Check if the server is currently running."""
        return self._running and self._server is not None

    async def start(self) -> None:
        """
        Start the TCP server.

        The server will begin accepting connections after this method returns.
        """
        if self._running:
            logger.warning("Server is already running")
            return

        self._server = await asyncio.start_server(
            self._handle_client,
            self.address,
            self.port,
        )

        self._running = True

        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
        logger.info(f"GCode Proxy Server started on {addrs}")

    async def serve_forever(self) -> None:
        """
        Run the server until it is stopped.

        This method blocks until stop() is called.
        """
        if not self._server:
            await self.start()

        if self._server:
            async with self._server:
                await self._server.serve_forever()

    async def stop(self) -> None:
        """
        Stop the server and close all connections.
        """
        self._running = False

        # Cancel all active connection handlers
        for task in self._active_connections:
            task.cancel()

        if self._active_connections:
            await asyncio.gather(*self._active_connections, return_exceptions=True)

        self._active_connections.clear()

        # Cancel all background tasks
        for task in self._background_tasks:
            task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        self._background_tasks.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("GCode Proxy Server stopped")

    def run_background(self, coroutine: Coroutine) -> None:
        """
        Run the server in the background as a task.
        """
        response_task = asyncio.create_task(coroutine)
        self._background_tasks.add(response_task)
        response_task.add_done_callback(self._background_tasks.discard)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """
        Handle an individual client connection.

        Args:
            reader: The stream reader for the client connection.
            writer: The stream writer for the client connection.
        """
        peername = writer.get_extra_info("peername")
        client_address = peername if peername else ("unknown", 0)

        logger.info(f"Client connected: {client_address}")

        cm = ConnectionManager()
        client_uuid = cm.register_client(writer)

        # Create a task for this connection and track it
        task = asyncio.current_task()
        if task:
            self._active_connections.add(task)

        try:
            await self._process_client_commands(reader, client_uuid, client_address)
        except asyncio.CancelledError:
            logger.info(f"Client connection cancelled: {client_address}")
        except Exception as e:
            logger.error(f"Error handling client {client_address}: {e}")
        finally:
            if task:
                self._active_connections.discard(task)

            cm.unregister_client(writer)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.info(f"Client disconnected: {client_address}")



    async def rate_limit_status_request(self, gcode: str) -> bool:
        """
        Count the currently queued status requests and signal a drop for the new one if needed
        """

        if gcode.strip() != "?":
            return False

        # Accessing private _queue to peek without consuming
        queue_items = list(self.device.task_queue._queue)  # type: ignore
        status_request_count = sum(
            1 for task in queue_items if task.command.strip() == "?"
        )

        if status_request_count > 0:
            return True
        return False

    async def _process_client_commands(
        self,
        reader: asyncio.StreamReader,
        client_uuid: str,
        client_address: tuple[str, int],
    ) -> None:
        """
        Process GCode commands from a client connection.

        Reads commands from the client, creates tasks, adds them to the queue,
        and schedules response sending asynchronously. This allows new commands
        to be queued and logged immediately without blocking on device responses.

        Args:
            reader: The stream reader for the client connection.
            client_uuid: The client's UUID.
            client_address: The client's address tuple.
        """
        while self._running:
            try:
                # Read data from client with a timeout
                data = await asyncio.wait_for(
                    reader.read(4096),
                    timeout=300.0,  # 5 minute idle timeout
                )

                if not data:
                    # Client closed connection
                    break

                # Decode and process the GCode commands
                raw_commands = data.decode("utf-8", errors="replace")

                log_gcode(raw_commands, f"{client_address}", "command TCP request")
                logger.debug(f"Received data from {client_address}: {raw_commands.strip()}")

                # Split into individual commands (handle both \n and \r\n)
                commands = [
                    cmd.strip()
                    for cmd in raw_commands.replace("\r\n", "\n").split("\n")
                    if cmd.strip()
                ]

                if not commands:
                    continue

                # Process each command by creating tasks and queuing them
                for command in commands:
                    try:
                        if await self.rate_limit_status_request(command):
                            logging.debug(
                                f"Dropping status `?` request from {client_address} "
                                "to avoid flooding the device"
                            )
                            continue

                        # Check if queue is at or above the limit
                        if self.device.queue_full():
                            logger.warning(
                                f"Queue full, rejecting command from {client_address}: {command}"
                            )
                            try:
                                limit = self.device.queue_maxsize()
                                error_response = f"error: command queue is full (limit: {limit})"
                                ConnectionManager().communicate(error_response, client_uuid)
                            except Exception:
                                pass
                            continue

                        # Create a task for this command
                        task = Task(
                            command=command,
                            client_uuid=client_uuid,
                            queue_task=not is_immediate_grbl_command(command),
                        )

                        await self.device.do_task(task)

                    except Exception as e:
                        error_msg = f"error: {e}"
                        logger.error(f"Error queuing command from {client_address}: {e}")
                        try:
                            error_response = f"{error_msg}\n"
                            ConnectionManager().communicate(error_response, client_uuid)
                        except Exception:
                            pass

            except asyncio.TimeoutError:
                logger.debug(f"Client {client_address} idle timeout")
                break
            except ConnectionResetError:
                logger.debug(f"Client {client_address} connection reset")
                break
            except Exception as e:
                logger.error(f"Error processing command from {client_address}: {e}")
                try:
                    error_response = f"error: {e}\n"
                    ConnectionManager().communicate(error_response, client_uuid)
                except Exception:
                    pass
                break
