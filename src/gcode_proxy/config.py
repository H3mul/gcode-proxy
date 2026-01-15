"""Configuration management for GCode Proxy Server.

Handles configuration loading with the following precedence (highest to lowest):
1. Environment variables
2. CLI arguments
3. Config file
4. Default values
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "gcode-proxy" / "config.yaml"

# Environment variable names
ENV_SERVER_PORT = "SERVER_PORT"
ENV_SERVER_ADDRESS = "SERVER_ADDRESS"
ENV_DEVICE_USB_ID = "DEVICE_USB_ID"
ENV_DEVICE_DEV_PATH = "DEVICE_DEV_PATH"
ENV_DEVICE_BAUD_RATE = "DEVICE_BAUD_RATE"
ENV_DEVICE_SERIAL_DELAY = "DEVICE_SERIAL_DELAY"
ENV_GCODE_LOG_FILE = "GCODE_LOG_FILE"
ENV_CONFIG_FILE = "GCODE_PROXY_CONFIG"


@dataclass
class ServerConfig:
    """Server configuration settings."""
    
    port: int = 8080
    address: str = "0.0.0.0"


@dataclass
class DeviceConfig:
    """USB device configuration settings."""
    
    usb_id: str | None = None
    path: str | None = None
    baud_rate: int = 115200
    serial_delay: float = 0.1
    gcode_log_file: str | None = None


@dataclass
class Config:
    """Main configuration container."""
    
    server: ServerConfig = field(default_factory=ServerConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    gcode_log_file: str | None = None
    
    @classmethod
    def load(
        cls,
        config_file: Path | str | None = None,
        cli_args: dict[str, Any] | None = None,
        skip_device_validation: bool = False,
    ) -> "Config":
        """Load configuration from all sources with proper precedence.
        
        Precedence (highest to lowest):
        1. Environment variables
        2. CLI arguments
        3. Config file
        4. Default values
        
        Args:
            config_file: Path to configuration file. If None, uses default or env var.
            cli_args: Dictionary of CLI arguments.
            skip_device_validation: If True, skip validation of device settings (for dry-run mode).
            
        Returns:
            Loaded and merged configuration.
            
        Raises:
            ValueError: If required usb_id is not set after loading all sources
                (unless skip_device_validation is True).
        """
        config = cls()
        
        # Determine config file path
        if config_file is None:
            config_file = os.environ.get(ENV_CONFIG_FILE, str(DEFAULT_CONFIG_PATH))
        
        config_path = Path(config_file).expanduser()
        
        # Load from config file if it exists
        if config_path.exists():
            config = cls._load_from_file(config_path)
        
        # Override with CLI arguments
        if cli_args:
            config = cls._apply_cli_args(config, cli_args)
        
        # Override with environment variables (highest precedence)
        config = cls._apply_env_vars(config)
        
        # Validate required configuration
        if not skip_device_validation:
            config._validate()
        
        return config
    
    @classmethod
    def _load_from_file(cls, path: Path) -> "Config":
        """Load configuration from YAML file.
        
        Args:
            path: Path to the YAML config file.
            
        Returns:
            Configuration loaded from file.
        """
        config = cls()
        
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            # Log warning and return defaults
            print(f"Warning: Failed to load config file {path}: {e}")
            return config
        
        # Parse server config
        if "server" in data:
            server_data = data["server"]
            if "port" in server_data:
                config.server.port = int(server_data["port"])
            if "address" in server_data:
                config.server.address = str(server_data["address"])
        
        # Parse device config
        if "device" in data:
            device_data = data["device"]
            if "usb-id" in device_data:
                config.device.usb_id = str(device_data["usb-id"])
            elif "usb_id" in device_data:
                config.device.usb_id = str(device_data["usb_id"])
            if "path" in device_data:
                config.device.path = str(device_data["path"])
            if "baud-rate" in device_data:
                config.device.baud_rate = int(device_data["baud-rate"])
            elif "baud_rate" in device_data:
                config.device.baud_rate = int(device_data["baud_rate"])
            if "serial-delay" in device_data:
                config.device.serial_delay = float(device_data["serial-delay"])
            elif "serial_delay" in device_data:
                config.device.serial_delay = float(device_data["serial_delay"])
            if "gcode-log-file" in device_data:
                config.device.gcode_log_file = str(device_data["gcode-log-file"])
            elif "gcode_log_file" in device_data:
                config.device.gcode_log_file = str(device_data["gcode_log_file"])
        
        # Parse gcode-log-file at root level
        if "gcode-log-file" in data:
            config.gcode_log_file = str(data["gcode-log-file"])
        elif "gcode_log_file" in data:
            config.gcode_log_file = str(data["gcode_log_file"])
        
        return config
    
    @classmethod
    def _apply_cli_args(cls, config: "Config", cli_args: dict[str, Any]) -> "Config":
        """Apply CLI arguments to configuration.
        
        Args:
            config: Existing configuration to modify.
            cli_args: Dictionary of CLI arguments.
            
        Returns:
            Modified configuration.
        """
        if cli_args.get("port") is not None:
            config.server.port = int(cli_args["port"])
        
        if cli_args.get("address") is not None:
            config.server.address = str(cli_args["address"])
        
        if cli_args.get("usb_id") is not None:
            config.device.usb_id = str(cli_args["usb_id"])
        
        if cli_args.get("dev_path") is not None:
            config.device.path = str(cli_args["dev_path"])
        
        if cli_args.get("baud_rate") is not None:
            config.device.baud_rate = int(cli_args["baud_rate"])
        
        if cli_args.get("serial_delay") is not None:
            config.device.serial_delay = float(cli_args["serial_delay"])
        
        if cli_args.get("gcode_log_file") is not None:
            config.gcode_log_file = str(cli_args["gcode_log_file"])
        
        return config
    
    @classmethod
    def _apply_env_vars(cls, config: "Config") -> "Config":
        """Apply environment variables to configuration.
        
        Args:
            config: Existing configuration to modify.
            
        Returns:
            Modified configuration.
        """
        if ENV_SERVER_PORT in os.environ:
            config.server.port = int(os.environ[ENV_SERVER_PORT])
        
        if ENV_SERVER_ADDRESS in os.environ:
            config.server.address = os.environ[ENV_SERVER_ADDRESS]
        
        if ENV_DEVICE_USB_ID in os.environ:
            config.device.usb_id = os.environ[ENV_DEVICE_USB_ID]
        
        if ENV_DEVICE_DEV_PATH in os.environ:
            config.device.path = os.environ[ENV_DEVICE_DEV_PATH]
        
        if ENV_DEVICE_BAUD_RATE in os.environ:
            config.device.baud_rate = int(os.environ[ENV_DEVICE_BAUD_RATE])
        
        if ENV_DEVICE_SERIAL_DELAY in os.environ:
            config.device.serial_delay = float(os.environ[ENV_DEVICE_SERIAL_DELAY])
        
        if ENV_GCODE_LOG_FILE in os.environ:
            config.gcode_log_file = os.environ[ENV_GCODE_LOG_FILE]
        
        return config
    
    def _validate(self) -> None:
        """Validate required configuration values.
        
        Raises:
            ValueError: If required configuration is missing or invalid.
        """
        usb_id_set = self.device.usb_id is not None and self.device.usb_id.strip()
        dev_path_set = self.device.path is not None and self.device.path.strip()
        
        if not usb_id_set and not dev_path_set:
            raise ValueError(
                "Either USB ID or device path is required but not set. Please provide one via:\n"
                "  USB ID:\n"
                "    - Environment variable: DEVICE_USB_ID\n"
                "    - CLI argument: --usb-id or -d\n"
                "    - Config file: device.usb-id\n"
                "  OR device path:\n"
                "    - Environment variable: DEVICE_DEV_PATH\n"
                "    - CLI argument: --dev\n"
                "    - Config file: device.path"
            )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration.
        """
        result: dict[str, Any] = {
            "server": {
                "port": self.server.port,
                "address": self.server.address,
            },
            "device": {
                "usb_id": self.device.usb_id,
                "path": self.device.path,
                "baud_rate": self.device.baud_rate,
                "serial_delay": self.device.serial_delay,
            },
        }
        if self.gcode_log_file is not None:
            result["gcode_log_file"] = self.gcode_log_file
        return result
    
    def save(self, path: Path | str | None = None) -> None:
        """Save configuration to YAML file.
        
        Args:
            path: Path to save to. If None, uses default config path.
        """
        if path is None:
            path = DEFAULT_CONFIG_PATH
        
        save_path = Path(path).expanduser()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to YAML-friendly format with hyphenated keys
        device_data: dict[str, Any] = {
            "baud-rate": self.device.baud_rate,
            "serial-delay": self.device.serial_delay,
        }
        
        # Only include usb-id if it's set
        if self.device.usb_id is not None:
            device_data["usb-id"] = self.device.usb_id
        
        # Only include path if it's set
        if self.device.path is not None:
            device_data["path"] = self.device.path
        
        data: dict[str, Any] = {
            "server": {
                "port": self.server.port,
                "address": self.server.address,
            },
            "device": device_data,
        }
        
        if self.gcode_log_file is not None:
            data["gcode-log-file"] = self.gcode_log_file
        
        with open(save_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
