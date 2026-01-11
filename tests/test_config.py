"""Tests for the configuration module."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from gcode_proxy.config import (
    Config,
    DeviceConfig,
    ServerConfig,
    DEFAULT_CONFIG_PATH,
    ENV_CONFIG_FILE,
    ENV_DEVICE_BAUD_RATE,
    ENV_DEVICE_USB_ID,
    ENV_SERVER_ADDRESS,
    ENV_SERVER_PORT,
)


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
        assert config.usb_id == "303a:4001"
        assert config.baud_rate == 115200

    def test_custom_values(self):
        """Test that DeviceConfig accepts custom values."""
        config = DeviceConfig(usb_id="1234:5678", baud_rate=9600)
        assert config.usb_id == "1234:5678"
        assert config.baud_rate == 9600


class TestConfig:
    """Tests for Config class."""

    def test_default_values(self):
        """Test that Config has correct default values."""
        config = Config()
        assert config.server.port == 8080
        assert config.server.address == "0.0.0.0"
        assert config.device.usb_id == "303a:4001"
        assert config.device.baud_rate == 115200

    def test_to_dict(self):
        """Test converting Config to dictionary."""
        config = Config()
        data = config.to_dict()
        
        assert data == {
            "server": {
                "port": 8080,
                "address": "0.0.0.0",
            },
            "device": {
                "usb_id": "303a:4001",
                "baud_rate": 115200,
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

    def test_load_from_nonexistent_file_uses_defaults(self):
        """Test that loading from a nonexistent file uses defaults."""
        config = Config.load(config_file="/nonexistent/path/config.yaml")
        assert config.server.port == 8080
        assert config.server.address == "0.0.0.0"
        assert config.device.usb_id == "303a:4001"
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
            config = Config.load(config_file=config_path)
            assert config.server.port == 9000
            assert config.server.address == "0.0.0.0"  # Default
            assert config.device.usb_id == "303a:4001"  # Default
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
        
        config = Config.load(cli_args=cli_args)
        
        assert config.server.port == 7000  # From env var
        assert config.server.address == "127.0.0.1"  # From CLI
        assert config.device.usb_id == "303a:4001"  # Default
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
        original.device.baud_rate = 57600
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            original.save(config_path)
            
            loaded = Config.load(config_file=config_path)
            
            assert loaded.server.port == original.server.port
            assert loaded.server.address == original.server.address
            assert loaded.device.usb_id == original.device.usb_id
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
            config = Config.load()
            
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
            config = Config.load(config_file=explicit_config_path)
            
            assert config.server.port == 2222
        finally:
            os.unlink(env_config_path)
            os.unlink(explicit_config_path)