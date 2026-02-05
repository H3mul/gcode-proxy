"""Tests for the configuration module."""

import os
import tempfile
from pathlib import Path

import yaml

from src.gcode_proxy.core.config import (
    Config,
    DeviceConfig,
    ServerConfig,
    ENV_CONFIG_FILE,
    ENV_DEVICE_BAUD_RATE,
    ENV_DEVICE_DEV_PATH,
    ENV_DEVICE_USB_ID,
    ENV_SERVER_ADDRESS,
    ENV_SERVER_PORT,
)
from src.gcode_proxy.trigger.triggers_config import CustomTriggerConfig, GCodeTriggerConfig


class TestServerConfig:
    """Tests for ServerConfig dataclass."""

    def test_default_values(self):
        """Test that ServerConfig has correct default values."""
        config = ServerConfig()
        assert config.port == 8080
        assert config.address == "0.0.0.0"

    def test_custom_values(self):
        """Test that ServerConfig accepts custom values."""
        config = ServerConfig(port=9000, address="127.0.0.1")
        assert config.port == 9000
        assert config.address == "127.0.0.1"


class TestDeviceConfig:
    """Tests for DeviceConfig dataclass."""

    def test_default_values(self):
        """Test that DeviceConfig has correct default values."""
        config = DeviceConfig()
        assert config.usb_id is None  # No default USB ID (for dry-run support)
        assert config.baud_rate == 115200

    def test_custom_values(self):
        """Test that DeviceConfig accepts custom values."""
        config = DeviceConfig(usb_id="1234:5678", baud_rate=9600)
        assert config.usb_id == "1234:5678"
        assert config.baud_rate == 9600

    def test_device_path(self):
        """Test that DeviceConfig accepts device path."""
        config = DeviceConfig(path="/dev/ttyACM0")
        assert config.path == "/dev/ttyACM0"
        assert config.usb_id is None


class TestConfig:
    """Tests for Config class."""

    def test_default_values(self):
        """Test that Config has correct default values."""
        config = Config()
        assert config.server.port == 8080
        assert config.server.address == "0.0.0.0"
        assert config.device.usb_id is None  # No default USB ID (for dry-run support)
        assert config.device.baud_rate == 115200

    def test_to_dict(self):
        """Test converting Config to dictionary."""
        config = Config()
        config.device.usb_id = "303a:4001"  # Set explicitly for test
        data = config.to_dict()
        
        assert data == {
            "server": {
                "port": 8080,
                "address": "0.0.0.0",
            },
            "device": {
                "usb_id": "303a:4001",
                "path": None,
                "baud_rate": 115200,
                "serial_delay": 100,
                "liveness_period": 1000.0,
                "swallow_realtime_ok": True,
            },
        }

    def test_to_dict_with_device_path(self):
        """Test converting Config to dictionary with device path."""
        config = Config()
        config.device.path = "/dev/ttyACM0"
        data = config.to_dict()
        
        assert data == {
            "server": {
                "port": 8080,
                "address": "0.0.0.0",
            },
            "device": {
                "usb_id": None,
                "path": "/dev/ttyACM0",
                "baud_rate": 115200,
                "serial_delay": 100,
                "liveness_period": 1000.0,
                "swallow_realtime_ok": True,
            },
        }


class TestConfigLoadFromFile:
    """Tests for loading configuration from files."""

    def test_load_from_yaml_file(self):
        """Test loading configuration from a YAML file."""
        config_data = {
            "server": {
                "port": 9000,
                "address": "192.168.1.1",
            },
            "device": {
                "usb-id": "abcd:1234",
                "baud-rate": 9600,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert config.server.port == 9000
            assert config.server.address == "192.168.1.1"
            assert config.device.usb_id == "abcd:1234"
            assert config.device.baud_rate == 9600
        finally:
            os.unlink(config_path)

    def test_load_from_yaml_with_device_path(self):
        """Test loading configuration from YAML with device path."""
        config_data = {
            "server": {
                "port": 9000,
            },
            "device": {
                "path": "/dev/ttyACM0",
                "baud-rate": 9600,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert config.server.port == 9000
            assert config.device.path == "/dev/ttyACM0"
            assert config.device.baud_rate == 9600
            assert config.device.usb_id is None
        finally:
            os.unlink(config_path)

    def test_load_from_yaml_with_underscore_keys(self):
        """Test loading configuration with underscore-style keys."""
        config_data = {
            "server": {
                "port": 9000,
                "address": "192.168.1.1",
            },
            "device": {
                "usb_id": "abcd:1234",
                "baud_rate": 9600,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert config.device.usb_id == "abcd:1234"
            assert config.device.baud_rate == 9600
        finally:
            os.unlink(config_path)

    def test_load_from_yaml_with_device_path_underscore(self):
        """Test loading configuration with underscore-style device path."""
        config_data = {
            "device": {
                "path": "/dev/ttyUSB0",
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert config.device.path == "/dev/ttyUSB0"
            assert config.device.usb_id is None
        finally:
            os.unlink(config_path)

    def test_load_from_nonexistent_file_uses_defaults(self):
        """Test that loading from a nonexistent file uses defaults."""
        # Use skip_device_validation since no usb_id is provided
        config = Config.load(
            config_file="/nonexistent/path/config.yaml",
            skip_device_validation=True,
        )
        assert config.server.port == 8080
        assert config.server.address == "0.0.0.0"
        assert config.device.usb_id is None  # No default USB ID
        assert config.device.baud_rate == 115200

    def test_load_partial_config_file(self):
        """Test loading a config file with only some values specified."""
        config_data = {
            "server": {
                "port": 9000,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            # Use skip_device_validation since no usb_id is provided
            config = Config.load(config_file=config_path, skip_device_validation=True)
            assert config.server.port == 9000
            assert config.server.address == "0.0.0.0"  # Default
            assert config.device.usb_id is None  # No default USB ID
            assert config.device.baud_rate == 115200  # Default
        finally:
            os.unlink(config_path)


class TestConfigLoadFromCliArgs:
    """Tests for loading configuration from CLI arguments."""

    def test_cli_args_override_defaults(self):
        """Test that CLI arguments override default values."""
        cli_args = {
            "port": 9000,
            "address": "127.0.0.1",
            "usb_id": "1111:2222",
            "baud_rate": 57600,
        }
        
        config = Config.load(cli_args=cli_args)
        assert config.server.port == 9000
        assert config.server.address == "127.0.0.1"
        assert config.device.usb_id == "1111:2222"
        assert config.device.baud_rate == 57600

    def test_cli_args_with_device_path(self):
        """Test that CLI arguments can set device path."""
        cli_args = {
            "port": 9000,
            "dev_path": "/dev/ttyACM0",
            "baud_rate": 57600,
        }
        
        config = Config.load(cli_args=cli_args)
        assert config.server.port == 9000
        assert config.device.path == "/dev/ttyACM0"
        assert config.device.baud_rate == 57600
        assert config.device.usb_id is None

    def test_cli_args_override_file(self):
        """Test that CLI arguments override file values."""
        config_data = {
            "server": {
                "port": 9000,
                "address": "192.168.1.1",
            },
            "device": {
                "usb-id": "abcd:1234",
                "baud-rate": 9600,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            cli_args = {
                "port": 8000,  # Override file value
            }
            config = Config.load(config_file=config_path, cli_args=cli_args)
            assert config.server.port == 8000  # From CLI
            assert config.server.address == "192.168.1.1"  # From file
            assert config.device.usb_id == "abcd:1234"  # From file
        finally:
            os.unlink(config_path)

    def test_cli_args_with_none_values_are_ignored(self):
        """Test that None values in CLI args don't override defaults."""
        cli_args = {
            "port": None,
            "address": None,
            "usb_id": "1111:2222",
            "baud_rate": None,
        }
        
        config = Config.load(cli_args=cli_args)
        assert config.server.port == 8080  # Default, not overridden
        assert config.server.address == "0.0.0.0"  # Default, not overridden
        assert config.device.usb_id == "1111:2222"  # Overridden
        assert config.device.baud_rate == 115200  # Default, not overridden

    def test_both_device_path_and_usb_id_path_is_used(self):
        """Test that setting both usb_id and path raises an error."""
        cli_args = {
            "usb_id": "1111:2222",
            "dev_path": "/dev/ttyACM0",
        }
        
        config = Config.load(cli_args=cli_args)
        assert config.device.usb_id == "1111:2222"
        assert config.device.path == "/dev/ttyACM0"

    def test_neither_usb_id_nor_path_raises_error(self):
        """Test that setting neither usb_id nor path raises an error."""
        import pytest
        with pytest.raises(ValueError, match="Either USB ID or device path is required"):
            Config.load(cli_args={})

    def test_device_path_alone_is_valid(self):
        """Test that device path alone is a valid configuration."""
        cli_args = {
            "dev_path": "/dev/ttyACM0",
        }
        
        config = Config.load(cli_args=cli_args)
        assert config.device.path == "/dev/ttyACM0"
        assert config.device.usb_id is None


class TestConfigLoadFromEnvVars:
    """Tests for loading configuration from environment variables."""

    def test_env_vars_override_all(self, monkeypatch):
        """Test that environment variables override everything."""
        # Set up a config file
        config_data = {
            "server": {
                "port": 9000,
                "address": "192.168.1.1",
            },
            "device": {
                "usb-id": "abcd:1234",
                "baud-rate": 9600,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            # Set environment variables
            monkeypatch.setenv(ENV_SERVER_PORT, "7000")
            monkeypatch.setenv(ENV_SERVER_ADDRESS, "10.0.0.1")
            monkeypatch.setenv(ENV_DEVICE_USB_ID, "ffff:eeee")
            monkeypatch.setenv(ENV_DEVICE_BAUD_RATE, "250000")
            
            # Also provide CLI args
            cli_args = {
                "port": 8000,
            }
            
            config = Config.load(config_file=config_path, cli_args=cli_args)
            
            # Env vars should override everything
            assert config.server.port == 7000
            assert config.server.address == "10.0.0.1"
            assert config.device.usb_id == "ffff:eeee"
            assert config.device.baud_rate == 250000
        finally:
            os.unlink(config_path)

    def test_env_vars_partial_override(self, monkeypatch):
        """Test that only set environment variables override values."""
        monkeypatch.setenv(ENV_SERVER_PORT, "7000")
        
        cli_args = {
            "address": "127.0.0.1",
        }
        
        # Use skip_device_validation since no usb_id is provided
        config = Config.load(cli_args=cli_args, skip_device_validation=True)
        
        assert config.server.port == 7000  # From env var
        assert config.server.address == "127.0.0.1"  # From CLI
        assert config.device.usb_id is None  # No default USB ID
        assert config.device.baud_rate == 115200  # Default


class TestConfigSave:
    """Tests for saving configuration to files."""

    def test_save_creates_file(self):
        """Test that save creates a config file."""
        config = Config()
        config.server.port = 9000
        config.device.usb_id = "1234:5678"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yaml"
            config.save(config_path)
            
            assert config_path.exists()
            
            with open(config_path) as f:
                saved_data = yaml.safe_load(f)
            
            assert saved_data["server"]["port"] == 9000
            assert saved_data["device"]["usb-id"] == "1234:5678"

    def test_save_with_device_path(self):
        """Test that save works with device path."""
        config = Config()
        config.server.port = 9000
        config.device.path = "/dev/ttyACM0"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yaml"
            config.save(config_path)
            
            assert config_path.exists()
            
            with open(config_path) as f:
                saved_data = yaml.safe_load(f)
            
            assert saved_data["server"]["port"] == 9000
            assert saved_data["device"]["path"] == "/dev/ttyACM0"
            assert "usb-id" not in saved_data["device"]

    def test_save_creates_parent_directories(self):
        """Test that save creates parent directories if needed."""
        config = Config()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "subdir" / "nested" / "config.yaml"
            config.save(config_path)
            
            assert config_path.exists()

    def test_roundtrip(self):
        """Test saving and loading produces the same configuration."""
        original = Config()
        original.server.port = 9000
        original.server.address = "192.168.1.1"
        original.device.usb_id = "aaaa:bbbb"
        original.device.path = None  # Explicitly clear path
        original.device.baud_rate = 57600
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            original.save(config_path)
            
            loaded = Config.load(config_file=config_path)
            
            assert loaded.server.port == original.server.port
            assert loaded.server.address == original.server.address
            assert loaded.device.usb_id == original.device.usb_id
            assert loaded.device.path is None
            assert loaded.device.baud_rate == original.device.baud_rate

    def test_roundtrip_with_device_path(self):
        """Test saving and loading with device path produces the same configuration."""
        original = Config()
        original.server.port = 9000
        original.device.path = "/dev/ttyACM0"
        original.device.usb_id = None  # Explicitly clear usb_id
        original.device.baud_rate = 57600
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            original.save(config_path)
            
            loaded = Config.load(config_file=config_path)
            
            assert loaded.server.port == original.server.port
            assert loaded.device.path == original.device.path
            assert loaded.device.usb_id is None
            assert loaded.device.baud_rate == original.device.baud_rate


class TestConfigFilePath:
    """Tests for config file path handling."""

    def test_env_var_for_config_path(self, monkeypatch):
        """Test that GCODE_PROXY_CONFIG env var sets the config path."""
        config_data = {
            "server": {
                "port": 9999,
            },
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            monkeypatch.setenv(ENV_CONFIG_FILE, config_path)
            
            # Load without specifying config_file - should use env var
            # Use skip_device_validation since no usb_id is provided
            config = Config.load(skip_device_validation=True)
            
            assert config.server.port == 9999
        finally:
            os.unlink(config_path)

    def test_explicit_path_overrides_env_var(self, monkeypatch):
        """Test that explicit config_file argument overrides env var."""
        # Create two config files
        env_config_data = {"server": {"port": 1111}}
        explicit_config_data = {"server": {"port": 2222}}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(env_config_data, f)
            env_config_path = f.name
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(explicit_config_data, f)
            explicit_config_path = f.name
        
        try:
            monkeypatch.setenv(ENV_CONFIG_FILE, env_config_path)
            
            # Load with explicit path - should ignore env var
            # Use skip_device_validation since no usb_id is provided
            config = Config.load(config_file=explicit_config_path, skip_device_validation=True)
            
            assert config.server.port == 2222
        finally:
            os.unlink(env_config_path)
            os.unlink(explicit_config_path)


class TestConfigWithTriggers:
    """Tests for loading trigger configurations from config files."""

    def test_load_with_custom_triggers(self):
        """Test loading configuration with custom triggers."""
        config_data = {
            "server": {
                "port": 9000,
            },
            "device": {
                "usb-id": "1234:5678",
            },
            "custom-triggers": [
                {
                    "id": "air-assist-on",
                    "trigger": {"type": "gcode", "match": "M8"},
                    "command": "script.py on",
                },
                {
                    "id": "air-assist-off",
                    "trigger": {"type": "gcode", "match": "M9"},
                    "command": "script.py off",
                },
            ],
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert len(config.custom_triggers) == 2
            assert config.custom_triggers[0].id == "air-assist-on"
            assert config.custom_triggers[0].trigger.match == "M8"
            assert config.custom_triggers[0].command == "script.py on"
            assert config.custom_triggers[1].id == "air-assist-off"
        finally:
            os.unlink(config_path)

    def test_load_with_invalid_trigger(self):
        """Test loading configuration with invalid trigger is skipped."""
        config_data = {
            "device": {
                "usb-id": "1234:5678",
            },
            "custom-triggers": [
                {
                    "id": "good-trigger",
                    "trigger": {"type": "gcode", "match": "M8"},
                    "command": "cmd",
                },
                {
                    "id": "bad-trigger",
                    "trigger": {"type": "gcode"},  # Missing match
                    "command": "cmd",
                },
            ],
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            # Invalid trigger should be skipped with warning
            config = Config.load(config_file=config_path)
            # Only the good trigger should be loaded
            assert len(config.custom_triggers) == 1
            assert config.custom_triggers[0].id == "good-trigger"
        finally:
            os.unlink(config_path)

    def test_load_empty_triggers_list(self):
        """Test loading configuration with empty triggers list."""
        config_data = {
            "device": {
                "usb-id": "1234:5678",
            },
            "custom-triggers": [],
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config_data, f)
            config_path = f.name
        
        try:
            config = Config.load(config_file=config_path)
            assert len(config.custom_triggers) == 0
        finally:
            os.unlink(config_path)

    def test_to_dict_with_triggers(self):
        """Test converting config with triggers to dictionary."""
        config = Config()
        config.device.usb_id = "1234:5678"
        config.custom_triggers = [
            CustomTriggerConfig(
                id="test",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="script.py",
            ),
        ]
        
        data = config.to_dict()
        assert "custom_triggers" in data
        assert len(data["custom_triggers"]) == 1
        assert data["custom_triggers"][0]["id"] == "test"
        assert data["custom_triggers"][0]["trigger"]["match"] == "M8"

    def test_save_and_load_with_triggers(self):
        """Test saving and loading configuration with triggers."""
        original = Config()
        original.server.port = 9000
        original.device.usb_id = "1234:5678"
        original.custom_triggers = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="cmd1.py",
            ),
            CustomTriggerConfig(
                id="trigger2",
                trigger=GCodeTriggerConfig(type="gcode", match="M9"),
                command="cmd2.py",
            ),
        ]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            original.save(config_path)
            
            loaded = Config.load(config_file=config_path)
            
            assert loaded.server.port == 9000
            assert loaded.device.usb_id == "1234:5678"
            assert len(loaded.custom_triggers) == 2
            assert loaded.custom_triggers[0].id == "trigger1"
            assert loaded.custom_triggers[0].trigger.match == "M8"
            assert loaded.custom_triggers[1].id == "trigger2"
