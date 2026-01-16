"""
TCP Server for GCode Proxy.

This module provides the async TCP server that accepts client connections
and forwards GCode commands to the task queue for processing by the device.
"""

import asyncio
import logging

from .task_queue import Task, TaskQueue


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
    ):
        """
        Initialize the GCode server.
        
        Args:
            task_queue: The TaskQueue for sending commands to the device.
            address: The address to bind the server to.
            port: The port to listen on.
            response_timeout: Timeout in seconds for waiting for device response.
        """
        self.task_queue = task_queue
        self.address = address
        self.port = port
        self.response_timeout = response_timeout
        
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
    
    async def _process_client_commands(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        client_address: tuple[str, int],
    ) -> None:
        """
        Process GCode commands from a client connection.
        
        Reads commands from the client, creates tasks, adds them to the queue,
        and sends responses back.
        
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
                    timeout=300.0  # 5 minute idle timeout
                )
                
                if not data:
                    # Client closed connection
                    break
                
                # Decode and process the GCode commands
                raw_commands = data.decode("utf-8", errors="replace")
                
                # Split into individual commands (handle both \n and \r\n)
                commands = [
                    cmd.strip()
                    for cmd in raw_commands.replace("\r\n", "\n").split("\n")
                    if cmd.strip()
                ]
                
                if not commands:
                    continue
                
                # Process each command by creating tasks and queuing them
                responses: list[str] = []
                
                for command in commands:
                    try:
                        # Create a task for this command
                        task = Task(
                            command=command,
                            client_address=client_address,
                            writer=writer,
                        )
                        
                        # Add task to the queue
                        await self.task_queue.put(task)
                        logger.debug(f"Queued command from {client_address}: {command}; " +
                            f"Queue size: {self.task_queue.qsize()}")
                        
                        # Wait for the response
                        response = await task.wait_for_response(timeout=self.response_timeout)
                        if response:
                            responses.append(response)
                            
                    except asyncio.TimeoutError:
                        error_msg = "error: timeout waiting for device response"
                        logger.error(f"Timeout for {client_address}: {command}")
                        responses.append(error_msg)
                        break
                    except Exception as e:
                        error_msg = f"error: {e}"
                        logger.error(f"Error for {client_address}: {e}")
                        responses.append(error_msg)
                        break
                
                # Send all responses back to the client
                if responses:
                    response_data = "\n".join(responses) + "\n"
                    writer.write(response_data.encode("utf-8"))
                    await writer.drain()
                    
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
