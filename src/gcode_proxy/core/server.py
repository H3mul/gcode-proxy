"""
TCP Server for GCode Proxy.

This module provides the async TCP server that accepts client connections
and forwards GCode commands to the task queue for processing by the device.
"""

import asyncio
import socket

from gcode_proxy.core.connection_manager import ConnectionManager
from gcode_proxy.core.logging import get_logger, log_tcp_recv
from gcode_proxy.core.task import GCodeTask, Task
from gcode_proxy.device import GCodeDevice
from gcode_proxy.trigger import TriggerManager

logger = get_logger()


class GCodeServer:
    """
    Async TCP server for receiving GCode commands from clients.

    This server accepts TCP connections, reads GCode commands,
    consults the trigger manager to build tasks, and forwards them
    to the device for processing.
    """

    def __init__(
        self,
        device: GCodeDevice,
        address: str = "0.0.0.0",
        port: int = 8080,
        response_timeout: float = 30.0,
    ):
        """
        Initialize the GCode server.

        Args:
            device: The GCodeDevice instance.
            address: The address to bind the server to.
            port: The port to listen on.
            response_timeout: Timeout in seconds for waiting for device response.

        Note:
            TriggerManager is accessed via singleton from the server methods.
        """
        self.device = device
        self.address = address
        self.port = port
        self.response_timeout = response_timeout

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

        for sock in self._server.sockets:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

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

    async def _process_client_commands(
        self,
        reader: asyncio.StreamReader,
        client_uuid: str,
        client_address: tuple[str, int],
    ) -> None:
        """
        Process GCode commands from a client connection.

        For each command received:
        1. Consult the trigger manager to see if any triggers match
        2. If triggers match, create the tasks they specify
        3. If no triggers match, create a simple GCodeTask
        4. Queue all tasks for the device to process

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

                logger.verbose(f"Received data from {client_address}: {raw_commands.strip()}")
                log_tcp_recv(raw_commands.strip(), client_address)

                # Split into individual commands (handle both \n and \r\n)
                commands = [
                    cmd.strip()
                    for cmd in raw_commands.replace("\r\n", "\n").split("\n")
                    if cmd.strip()
                ]

                if not commands:
                    continue

                # Process each command by checking triggers and building tasks
                for command in commands:
                    try:
                        await self._queue_command(command, client_uuid, client_address)

                    except Exception as e:
                        error_msg = f"error: {e}"
                        logger.error(f"Error queuing command from {client_address}: {e}")
                        try:
                            error_response = f"{error_msg}\n"
                            ConnectionManager().communicate(error_response, client_uuid)
                        except Exception:
                            pass

            except asyncio.TimeoutError:
                logger.debug(f"Client {client_address} data read idle timeout")
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

    async def _queue_command(
        self,
        command: str,
        client_uuid: str,
        client_address: tuple[str, int],
    ) -> None:
        """
        Queue a command by checking triggers and building appropriate tasks.

        If triggers match, builds tasks from trigger configuration.
        If no triggers match, creates a simple GCodeTask.

        Args:
            command: The GCode command string.
            client_uuid: The UUID of the client.
            client_address: The client's address tuple.
        """
        # Check if queue is at limit before processing
        if self.device.queue_full():
            logger.warning(f"Queue full, rejecting command from {client_address}: {command}")
            try:
                limit = self.device.queue_maxsize()
                error_response = f"error: command queue is full (limit: {limit})"
                ConnectionManager().communicate(error_response, client_uuid)
            except Exception:
                pass
            return

        # Check for triggers using the singleton trigger manager
        tasks_to_queue: list[Task] | None = None
        trigger_manager = TriggerManager.get_instance()
        if trigger_manager and trigger_manager.triggers:
            tasks_to_queue = trigger_manager.build_tasks_for_gcode(
                command,
                client_uuid,
            )

        # If no triggers matched, create a simple GCodeTask
        if tasks_to_queue is None:
            task = GCodeTask(
                client_uuid=client_uuid,
                gcode=command,
                should_respond=True,
            )
            tasks_to_queue = [task]

        logger.debug(
            f"Built {len(tasks_to_queue)} tasks for command from {client_address}: "
            f"{command}"
        )
        logger.debug(f"Tasks: {repr(tasks_to_queue)}")

        # Queue all tasks for processing
        for task in tasks_to_queue:
            await self.device.do_task(task)
