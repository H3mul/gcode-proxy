"""
TCP Server for GCode Proxy.

This module provides the async TCP server that accepts client connections
and forwards GCode commands to the task queue for processing by the device.
"""

import asyncio
import logging

from gcode_proxy.utils import detect_grbl_soft_reset
from .task_queue import Task, TaskQueue, empty_queue
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
        task_queue: TaskQueue,
        address: str = "0.0.0.0",
        port: int = 8080,
        response_timeout: float = 30.0,
        queue_limit: int = 50,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the GCode server.

        Args:
            task_queue: The TaskQueue for sending commands to the device.
            address: The address to bind the server to.
            port: The port to listen on.
            response_timeout: Timeout in seconds for waiting for device response.
            queue_limit: Maximum number of commands allowed in the queue.
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
        """
        self.task_queue = task_queue
        self.address = address
        self.port = port
        self.response_timeout = response_timeout
        self.queue_limit = queue_limit
        self.normalize_grbl_responses = normalize_grbl_responses

        self._server: asyncio.Server | None = None
        self._running = False
        self._active_connections: set[asyncio.Task] = set()

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

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("GCode Proxy Server stopped")

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

        # Create a task for this connection and track it
        task = asyncio.current_task()
        if task:
            self._active_connections.add(task)

        try:
            await self._process_client_commands(reader, writer, client_address)
        except asyncio.CancelledError:
            logger.info(f"Client connection cancelled: {client_address}")
        except Exception as e:
            logger.error(f"Error handling client {client_address}: {e}")
        finally:
            if task:
                self._active_connections.discard(task)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            logger.info(f"Client disconnected: {client_address}")

    async def _send_response_when_ready(self, task: Task, timeout: float) -> None:
        """
        Wait for a task's response and send it back to the client.

        This method is scheduled asynchronously to allow the server to continue
        accepting and queuing new commands without blocking on device responses.

        Args:
            task: The Task object to wait for.
            timeout: Timeout in seconds for waiting for the response.
        """
        try:
            response = await task.wait_for_response(timeout=timeout)
            await task.send_response_to_client(response)
        except asyncio.TimeoutError:
            error_msg = "error: timeout waiting for device response"
            logger.error(f"Timeout for {task.client_address}: {task.command}")
            await task.send_response_to_client(error_msg)
        except Exception as e:
            error_msg = f"error: {e}"
            logger.error(f"Error sending response for {task.client_address}: {e}")
            await task.send_response_to_client(error_msg)

    async def rate_limit_status_request(self, gcode: str) -> bool:
        """
        Count the currently queued status requests and signal a drop for the new one if needed
        """

        if gcode.strip() != "?":
            return False

        status_request_count = sum(
            1 for task in list(self.task_queue._queue) if task.command.strip() == "?"
        )

        if status_request_count > 0:
            return True
        return False

    async def handle_soft_reset(self, gcode: str) -> None:
        if not detect_grbl_soft_reset(gcode):
            return

        logging.info("Soft reset received, clearing command queue")

        if self.task_queue:
            empty_queue(self.task_queue)

    async def _process_client_commands(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        client_address: tuple[str, int],
    ) -> None:
        """
        Process GCode commands from a client connection.

        Reads commands from the client, creates tasks, adds them to the queue,
        and schedules response sending asynchronously. This allows new commands
        to be queued and logged immediately without blocking on device responses.

        Args:
            reader: The stream reader for the client connection.
            writer: The stream writer for the client connection.
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
                        await self.handle_soft_reset(command)
                        if await self.rate_limit_status_request(command):
                            logging.debug(f"Dropping status `?` request from {client_address} to avoid flooding the device")
                            continue

                        # Check if queue is at or above the limit
                        if self.task_queue.qsize() >= self.queue_limit:
                            error_msg = f"error: command queue is full (limit: {self.queue_limit})"
                            logger.warning(
                                f"Queue full, rejecting command from {client_address}: {command}"
                            )
                            try:
                                error_response = f"{error_msg}\n"
                                writer.write(error_response.encode("utf-8"))
                                await writer.drain()
                            except Exception:
                                pass
                            continue

                        # Create a task for this command
                        task = Task(
                            command=command,
                            client_address=client_address,
                            writer=writer,
                        )

                        # Add task to the queue
                        await self.task_queue.put(task)
                        logger.debug(
                            f"Queued command from {client_address}: {repr(command)}; "
                            + f"Queue size: {self.task_queue.qsize()}"
                        )

                        # Schedule response sending asynchronously without awaiting
                        # This allows the server to immediately process new incoming commands
                        asyncio.create_task(
                            self._send_response_when_ready(task, self.response_timeout)
                        )

                    except Exception as e:
                        error_msg = f"error: {e}"
                        logger.error(f"Error queuing command from {client_address}: {e}")
                        try:
                            error_response = f"{error_msg}\n"
                            writer.write(error_response.encode("utf-8"))
                            await writer.drain()
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
                    writer.write(error_response.encode("utf-8"))
                    await writer.drain()
                except Exception:
                    pass
                break
