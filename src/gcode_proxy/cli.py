"""
Command-line interface for GCode Proxy Server.

This module provides the CLI using Click, supporting configuration via:
1. Environment variables (highest precedence)
2. CLI arguments
3. Config file
4. Default values (lowest precedence)
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

import click

from gcode_proxy.core.config import (
    DEFAULT_CONFIG_PATH,
    ENV_CONFIG_FILE,
    ENV_DEVICE_BAUD_RATE,
    ENV_DEVICE_DEV_PATH,
    ENV_DEVICE_LIVENESS_PERIOD,
    ENV_DEVICE_RESPONSE_TIMEOUT,
    ENV_DEVICE_SERIAL_DELAY,
    ENV_DEVICE_STATUS_BEHAVIOR,
    ENV_DEVICE_SWALLOW_REALTIME_OK,
    ENV_DEVICE_USB_ID,
    ENV_GCODE_LOG_FILE,
    ENV_TCP_LOG_FILE,
    ENV_SERVER_ADDRESS,
    ENV_SERVER_PORT,
    ENV_SERVER_QUEUE_LIMIT,
    Config,
)
from gcode_proxy.core.logging import setup_logging, get_logger
from gcode_proxy.core.service import GCodeProxyService
from gcode_proxy.trigger import TriggerManager


@click.command()
@click.option(
    "-c", "--config",
    "config_file",
    type=click.Path(exists=False, path_type=Path),
    envvar=ENV_CONFIG_FILE,
    default=None,
    help=f"Path to configuration file. [default: {DEFAULT_CONFIG_PATH}] [env: {ENV_CONFIG_FILE}]",
)
@click.option(
    "-p", "--port",
    type=int,
    default=None,
    help=f"TCP server port. [env: {ENV_SERVER_PORT}]",
)
@click.option(
    "-a", "--address",
    type=str,
    default=None,
    help=f"TCP server bind address. [env: {ENV_SERVER_ADDRESS}]",
)
@click.option(
    "--queue-limit",
    type=int,
    default=None,
    help=f"Command queue size limit (default: 50). [env: {ENV_SERVER_QUEUE_LIMIT}]",
)
@click.option(
    "-d", "--device", "--usb-id",
    "usb_id",
    type=str,
    default=None,
    help=f"USB device ID in vendor:product format (e.g., 303a:4001). [env: {ENV_DEVICE_USB_ID}]",
)
@click.option(
    "--dev",
    "dev_path",
    type=str,
    default=None,
    help=(
        f"Device path (e.g., /dev/ttyACM0). "
        f"Mutually exclusive with --usb-id. [env: {ENV_DEVICE_DEV_PATH}]"
    ),
)
@click.option(
    "-b", "--baud-rate",
    type=int,
    default=None,
    help=f"Serial baud rate. [env: {ENV_DEVICE_BAUD_RATE}]",
)
@click.option(
    "--serial-delay",
    type=float,
    default=None,
    help=f"Device initialization delay in ms. [env: {ENV_DEVICE_SERIAL_DELAY}]",
)
@click.option(
    "--response-timeout",
    type=float,
    default=None,
    help=(
        f"Timeout in ms for waiting for device response (default: 30s). "
        f"[env: {ENV_DEVICE_RESPONSE_TIMEOUT}]"
    ),
)
@click.option(
    "--liveness-period",
    type=float,
    default=None,
    help=(
        f"Period in ms for pinging device with `?` command (default: 200ms). "
        f"[env: {ENV_DEVICE_LIVENESS_PERIOD}]"
    ),
)
@click.option(
    "--swallow-realtime-ok",
    type=bool,
    default=None,
    help=(
        f"Suppress 'ok' responses from `?` commands to avoid buffer conflicts "
        f"(default: true). [env: {ENV_DEVICE_SWALLOW_REALTIME_OK}]"
    ),
)
@click.option(
    "--status-behavior",
    type=str,
    default=None,
    help=(
        f"Status query behavior: 'liveness-cache' or 'forward'. "
        f"[env: {ENV_DEVICE_STATUS_BEHAVIOR}]"
    ),
)
@click.option(
    "--gcode-log-file",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to file for logging all GCode communication. [env: {ENV_GCODE_LOG_FILE}]",
)
@click.option(
    "--tcp-log-file",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to file for logging all TCP communication. [env: {ENV_TCP_LOG_FILE}]",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Run in dry-run mode without actual serial device communication.",
)
@click.option(
    "-v", "--verbose",
    count=True,
    default=0,
    help="Increase verbosity level (-v for DEBUG, -vv for VERBOSE).",
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    default=False,
    help="Suppress all output except errors.",
)
@click.option(
    "--generate-config",
    is_flag=True,
    default=False,
    help="Generate a default configuration file and exit.",
)
@click.version_option(package_name="gcode-proxy")
def main(
    config_file: Path | None,
    port: int | None,
    address: str | None,
    queue_limit: int | None,
    usb_id: str | None,
    dev_path: str | None,
    baud_rate: int | None,
    serial_delay: float | None,
    response_timeout: float | None,
    liveness_period: float | None,
    swallow_realtime_ok: bool | None,
    status_behavior: str | None,
    gcode_log_file: Path | None,
    tcp_log_file: Path | None,
    dry_run: bool,
    verbose: int,
    quiet: bool,
    generate_config: bool,
) -> None:
    """
    GCode Proxy Server - Forward GCode commands from TCP clients to USB serial devices.

    This server acts as a middleman between GCode stream sources (such as CAM software
    or network-based senders) and USB-connected devices (such as 3D printers or CNC machines).

    Configuration is loaded with the following precedence (highest to lowest):

    \b
    1. Environment variables
    2. CLI arguments
    3. Configuration file
    4. Default values

    Example usage:

    \b
        # Start with default settings
        gcode-proxy-server

        # Specify device and port
        gcode-proxy-server --device 303a:4001 --port 9000

        # Use a custom config file
        gcode-proxy-server --config /etc/gcode-proxy/config.yaml

        # Run in dry-run mode (no actual hardware)
        gcode-proxy-server --dry-run

        # Generate a default config file
        gcode-proxy-server --generate-config
    """
    # Set up basic logging first (before config is loaded)
    setup_logging(verbosity_level=verbose, quiet=quiet)
    logger = get_logger()

    # Build CLI args dict for config loading
    cli_args: dict[str, Any] = {}
    if port is not None:
        cli_args["port"] = port
    if address is not None:
        cli_args["address"] = address
    if queue_limit is not None:
        cli_args["queue_limit"] = queue_limit
    if usb_id is not None:
        cli_args["usb_id"] = usb_id
    if dev_path is not None:
        cli_args["dev_path"] = dev_path
    if baud_rate is not None:
        cli_args["baud_rate"] = baud_rate
    if serial_delay is not None:
        cli_args["serial_delay"] = serial_delay

    if response_timeout is not None:
        cli_args["response_timeout"] = response_timeout

    if liveness_period is not None:
        cli_args["liveness_period"] = liveness_period

    if swallow_realtime_ok is not None:
        cli_args["swallow_realtime_ok"] = swallow_realtime_ok

    if status_behavior is not None:
        cli_args["status_behavior"] = status_behavior

    if gcode_log_file is not None:
        cli_args["gcode_log_file"] = str(gcode_log_file)

    if tcp_log_file is not None:
        cli_args["tcp_log_file"] = str(tcp_log_file)

    try:
        # Load configuration (skip device validation in dry-run mode)
        config = Config.load(
            config_file=config_file,
            cli_args=cli_args,
            skip_device_validation=dry_run,
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Now set up file logging with the loaded configuration
    setup_logging(
        verbosity_level=verbose,
        quiet=quiet,
        gcode_log_file=config.gcode_log_file,
        tcp_log_file=config.tcp_log_file,
    )

    # Handle --generate-config
    if generate_config:
        target_path = config_file if config_file else DEFAULT_CONFIG_PATH
        try:
            config.save(target_path)
            click.echo(f"Configuration file generated: {target_path}")
        except Exception as e:
            click.echo(f"Error generating config file: {e}", err=True)
            sys.exit(1)
        return

    # Log the configuration being used
    logger.info("Starting GCode Proxy Server")
    if dry_run:
        logger.info("  Mode: DRY-RUN (no actual hardware communication)")
    else:
        device_info = config.device.path if config.device.path else config.device.usb_id
        logger.info(f"  Device: {device_info} @ {config.device.baud_rate} baud")
        logger.info(f"  Serial delay: {config.device.serial_delay}ms")
        logger.info(f"  Response timeout: {config.device.response_timeout}ms")
        logger.info(f"  Liveness period: {config.device.liveness_period}ms")
        logger.info(f"  Swallow realtime ok: {config.device.swallow_realtime_ok}")
    logger.info(f"  Server: {config.server.address}:{config.server.port}")
    logger.info(f"  Queue limit: {config.server.queue_limit}")
    if config.gcode_log_file:
        logger.info(f"  GCode log file: {config.gcode_log_file}")
    if config.tcp_log_file:
        logger.info(f"  TCP log file: {config.tcp_log_file}")
    if config.custom_triggers:
        logger.info(f"  Custom triggers: {len(config.custom_triggers)} configured")

    # Create trigger manager if triggers are configured
    trigger_manager = None
    if config.custom_triggers:
        try:
            trigger_manager = TriggerManager(config.custom_triggers)
        except ValueError as e:
            logger.error(f"Failed to load triggers: {e}")
            sys.exit(1)

    # Create the service based on mode
    if dry_run:
        service = GCodeProxyService.create_dry_run(
            address=config.server.address,
            port=config.server.port,
            gcode_log_file=config.gcode_log_file,
            queue_limit=config.server.queue_limit,
        )
    else:
        # Either usb_id or dev_path is guaranteed to be set after validation
        # (when not in dry-run mode)
        service = GCodeProxyService.create_serial(
            usb_id=config.device.usb_id,
            dev_path=config.device.path,
            baud_rate=config.device.baud_rate,
            serial_delay=config.device.serial_delay,
            address=config.server.address,
            port=config.server.port,
            gcode_log_file=config.gcode_log_file,
            queue_limit=config.server.queue_limit,
            liveness_period=config.device.liveness_period,
            swallow_realtime_ok=config.device.swallow_realtime_ok,
            status_behavior=config.device.status_behavior,
        )
        service.trigger_manager = trigger_manager

    # Set up signal handlers for graceful shutdown
    class ExitSignal(Exception):  # noqa: N818
        pass

    def handle_signal(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        raise ExitSignal()

    # Register signal handlers
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGHUP, handle_signal)

    # Run the async service
    try:
        asyncio.run(run_service(service))
    except (ExitSignal, KeyboardInterrupt):
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if verbose > 0:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    logger.info("GCode Proxy Server stopped")


async def run_service(service: GCodeProxyService) -> None:
    """
    Run the proxy service with proper signal handling.

    Args:
        service: The GCodeProxyService instance to run.
    """
    logger = get_logger()

    # Set up async signal handlers on Unix
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    async def shutdown_service_on_stop() -> None:
        await stop_event.wait()

        # Clean shutdown
        await service.stop()

    asyncio.create_task(shutdown_service_on_stop())

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        await service.start()
        await stop_event.wait()
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    main()
