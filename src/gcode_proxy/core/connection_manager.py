"""
Connection Manager for GCode Proxy.

This module provides the ConnectionManager class which handles TCP interactions,
client registration, and broadcasting messages.
"""

from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass
from enum import Enum, auto

from gcode_proxy.core.logging import get_logger, log_tcp_sent

logger = get_logger()


class ConnectionAction(Enum):
    """Actions that can be performed on a connection."""
    SEND_DATA = auto()
    CLOSE_SOCKET = auto()
    SEND_AND_CLOSE = auto()


@dataclass
class ConnectionTask:
    """
    Task to be performed by the connection manager.

    Attributes:
        action: The action to perform.
        target_uuid: The UUID of the target connection (None for broadcast).
        data: The data to send (if applicable).
    """
    action: ConnectionAction
    target_uuid: str | None = None
    data: str | None = None


class ConnectionManager:
    """
    Manages TCP connections and handles communication with clients.

    This class maintains a registry of active connections mapped to UUIDs
    and provides methods to send data to specific clients or broadcast
    to all connected clients.
    """

    _instance: ConnectionManager | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self.writer_to_uuid: dict[asyncio.StreamWriter, str] = {}
        self.uuid_to_writer: dict[str, asyncio.StreamWriter] = {}
        self.task_queue: asyncio.Queue[ConnectionTask] = asyncio.Queue()
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._initialized = True

    def register_client(self, writer: asyncio.StreamWriter) -> str:
        """
        Register a new TCP client.

        Args:
            writer: The StreamWriter for the client.

        Returns:
            The assigned UUID for the client.
        """
        if writer in self.writer_to_uuid:
            return self.writer_to_uuid[writer]

        client_uuid = str(uuid.uuid4())
        self.writer_to_uuid[writer] = client_uuid
        self.uuid_to_writer[client_uuid] = writer
        return client_uuid

    def unregister_client(self, writer: asyncio.StreamWriter) -> None:
        """
        Unregister a TCP client.

        Args:
            writer: The StreamWriter to unregister.
        """
        if writer in self.writer_to_uuid:
            client_uuid = self.writer_to_uuid[writer]
            del self.writer_to_uuid[writer]
            if client_uuid in self.uuid_to_writer:
                del self.uuid_to_writer[client_uuid]

    def get_client_address(self, client_uuid: str) -> tuple[str, int] | None:
        """
        Get the address of a client by UUID.

        Args:
            client_uuid: The UUID of the client.

        Returns:
            The client address tuple or None if not found.
        """
        writer = self.uuid_to_writer.get(client_uuid)
        if writer:
            return writer.get_extra_info("peername")
        return None

    def get_client_address_str(self, client_uuid: str) -> str:
        """
        Get the address of a client by UUID as a string.

        Args:
            client_uuid: The UUID of the client.
        """

        client_address = self.get_client_address(client_uuid)
        return f"{client_address[0]}:{client_address[1]}"

    def submit_task(self, task: ConnectionTask) -> None:
        """
        Submit a task to the connection manager.

        Args:
            task: The ConnectionTask to execute.
        """
        self.task_queue.put_nowait(task)

    def communicate(
        self,
        data: str | None = None,
        target: str | None = None,
        action: ConnectionAction = ConnectionAction.SEND_DATA,
    ) -> None:
        """
        Shortcut method for adding tasks to the queue.
        Non-blocking, returns immediately, sends data at a later date

        Args:
            data: Data string to send.
            target: Target UUID (empty string or None for broadcast).
            action: Action to perform.
        """
        target_uuid = target if target else None
        self.submit_task(ConnectionTask(action=action, target_uuid=target_uuid, data=data))

    def broadcast(
        self,
        data: str,
        action: ConnectionAction = ConnectionAction.SEND_DATA,
    ) -> None:
        """
        Broadcast data to all connected clients.

        Args:
            data: Data string to send.
            action: Action to perform.
        """
        self.communicate(data=data, target=None, action=action)

    def close_all_connections(self) -> None:
        """
        Close the connection for a specific client.

        Args:
            target_uuid: The UUID of the target client.
        """
        self.communicate(data=None, target=None, action=ConnectionAction.CLOSE_SOCKET)

    async def start(self) -> None:
        """Start the connection manager worker."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("Connection Manager started")

    async def stop(self) -> None:
        """Stop the connection manager and close all connections."""
        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        # Close all active connections
        writers = list(self.writer_to_uuid.keys())
        for writer in writers:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logger.error(f"Error closing connection during shutdown: {e}")

        self.writer_to_uuid.clear()
        self.uuid_to_writer.clear()
        logger.info("Connection Manager stopped")

    async def _process_queue(self) -> None:
        """Process tasks from the queue."""
        while self._running:
            try:
                task = await self.task_queue.get()
                await self._handle_task(task)
                self.task_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing connection task: {e}")

    async def _handle_task(self, task: ConnectionTask) -> None:
        """Handle a single connection task."""
        writers: list[asyncio.StreamWriter] = []

        if task.target_uuid is None:
            # Broadcast to all
            writers = list(self.writer_to_uuid.keys())
        else:
            # Target specific client
            writer = self.uuid_to_writer.get(task.target_uuid)
            if writer:
                writers = [writer]
            else:
                logger.warning(f"Target UUID {task.target_uuid} not found for task {task.action}")
                return

        for writer in writers:
            try:
                if task.action in (ConnectionAction.SEND_DATA, ConnectionAction.SEND_AND_CLOSE):
                    if task.data:
                        data = task.data
                        if not data.endswith('\n'):
                            data += '\n'
                        writer.write(data.encode('utf-8'))
                        await writer.drain()

                        log_tcp_sent(data.strip(), self.get_client_address(task.target_uuid))

                if task.action in (ConnectionAction.CLOSE_SOCKET, ConnectionAction.SEND_AND_CLOSE):
                    writer.close()
                    await writer.wait_closed()
                    self.unregister_client(writer)

            except Exception as e:
                logger.exception(f"Error handling connection action for client: {e}")
                self.unregister_client(writer)
