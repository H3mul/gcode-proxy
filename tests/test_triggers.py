"""Tests for the trigger configuration and functionality."""

import asyncio

import pytest

from src.gcode_proxy.trigger import Trigger
from src.gcode_proxy.trigger_manager import TriggerManager
from src.gcode_proxy.triggers_config import CustomTriggerConfig, GCodeTriggerConfig


class TestGCodeTriggerConfig:
    """Tests for GCodeTriggerConfig dataclass."""

    def test_create_from_dict_valid(self):
        """Test creating a valid GCodeTriggerConfig from dict."""
        data = {"type": "gcode", "match": "M8"}
        config = GCodeTriggerConfig.from_dict(data)
        assert config.type == "gcode"
        assert config.match == "M8"

    def test_create_from_dict_missing_type(self):
        """Test that missing type raises ValueError."""
        data = {"match": "M8"}
        with pytest.raises(ValueError, match="'type' is required"):
            GCodeTriggerConfig.from_dict(data)

    def test_create_from_dict_missing_match(self):
        """Test that missing match raises ValueError."""
        data = {"type": "gcode"}
        with pytest.raises(ValueError, match="'match' pattern is required"):
            GCodeTriggerConfig.from_dict(data)

    def test_create_from_dict_empty_type(self):
        """Test that empty type raises ValueError."""
        data = {"type": "", "match": "M8"}
        with pytest.raises(ValueError, match="'type' is required"):
            GCodeTriggerConfig.from_dict(data)

    def test_create_from_dict_unsupported_type(self):
        """Test that unsupported trigger type raises ValueError."""
        data = {"type": "timer", "match": "M8"}
        with pytest.raises(ValueError, match="Unsupported trigger type"):
            GCodeTriggerConfig.from_dict(data)




class TestCustomTriggerConfig:
    """Tests for CustomTriggerConfig dataclass."""

    def test_create_from_dict_valid(self):
        """Test creating a valid CustomTriggerConfig from dict."""
        data = {
            "id": "air-assist-on",
            "trigger": {"type": "gcode", "match": "M8"},
            "command": "script.py",
        }
        config = CustomTriggerConfig.from_dict(data)
        assert config.id == "air-assist-on"
        assert config.trigger.type == "gcode"
        assert config.trigger.match == "M8"
        assert config.command == "script.py"

    def test_create_from_dict_missing_id(self):
        """Test that missing id raises ValueError."""
        data = {
            "trigger": {"type": "gcode", "match": "M8"},
            "command": "script.py",
        }
        with pytest.raises(ValueError, match="'id' is required"):
            CustomTriggerConfig.from_dict(data)

    def test_create_from_dict_missing_trigger(self):
        """Test that missing trigger raises ValueError."""
        data = {
            "id": "air-assist-on",
            "command": "script.py",
        }
        with pytest.raises(ValueError, match="missing 'trigger' configuration"):
            CustomTriggerConfig.from_dict(data)

    def test_create_from_dict_missing_command(self):
        """Test that missing command raises ValueError."""
        data = {
            "id": "air-assist-on",
            "trigger": {"type": "gcode", "match": "M8"},
        }
        with pytest.raises(ValueError, match="missing 'command'"):
            CustomTriggerConfig.from_dict(data)

    def test_create_from_dict_invalid_trigger(self):
        """Test that invalid trigger config raises ValueError."""
        data = {
            "id": "air-assist-on",
            "trigger": {"type": "invalid"},
            "command": "script.py",
        }
        with pytest.raises(ValueError, match="invalid configuration"):
            CustomTriggerConfig.from_dict(data)




class TestTrigger:
    """Tests for Trigger class."""

    def test_init_valid(self):
        """Test creating a trigger with valid config."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="echo test",
        )
        trigger = Trigger(config)
        assert trigger.id == "test"
        assert trigger.command == "echo test"

    def test_init_invalid_regex(self):
        """Test that invalid regex pattern raises ValueError."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="[invalid(regex"),
            command="echo test",
        )
        with pytest.raises(ValueError, match="invalid regex pattern"):
            Trigger(config)

    def test_matches_exact(self):
        """Test matching an exact GCode."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="echo test",
        )
        trigger = Trigger(config)
        assert trigger.matches("M8")
        assert trigger.matches("M8\n")
        assert trigger.matches("  M8  ")

    def test_matches_case_sensitive(self):
        """Test that matching is case sensitive."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="echo test",
        )
        trigger = Trigger(config)
        assert trigger.matches("M8")
        assert not trigger.matches("m8")

    def test_matches_regex_pattern(self):
        """Test matching with regex pattern."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M[89]"),
            command="echo test",
        )
        trigger = Trigger(config)
        assert trigger.matches("M8")
        assert trigger.matches("M9")
        assert not trigger.matches("M7")

    def test_matches_partial(self):
        """Test matching as partial match in command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="G1.*X"),
            command="echo test",
        )
        trigger = Trigger(config)
        assert trigger.matches("G1 X10 Y20")
        assert trigger.matches("G1X10")
        assert not trigger.matches("G1 Y20")

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test executing a successful command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="exit 0",
        )
        trigger = Trigger(config)
        result = await trigger.execute()
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """Test executing a failed command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="exit 1",
        )
        trigger = Trigger(config)
        result = await trigger.execute()
        assert result is False

    @pytest.mark.asyncio
    async def test_execute_nonexistent_command(self):
        """Test executing a nonexistent command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="nonexistent_command_12345",
        )
        trigger = Trigger(config)
        result = await trigger.execute()
        assert result is False


class TestTriggerManager:
    """Tests for TriggerManager class."""

    def test_init_empty(self):
        """Test creating an empty trigger manager."""
        manager = TriggerManager()
        assert len(manager.triggers) == 0

    def test_init_with_triggers(self):
        """Test creating trigger manager with triggers."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="cmd1",
            ),
            CustomTriggerConfig(
                id="trigger2",
                trigger=GCodeTriggerConfig(type="gcode", match="M9"),
                command="cmd2",
            ),
        ]
        manager = TriggerManager(configs)
        assert len(manager.triggers) == 2
        assert manager.triggers[0].id == "trigger1"
        assert manager.triggers[1].id == "trigger2"

    def test_init_with_invalid_trigger(self):
        """Test that invalid trigger raises ValueError."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="[invalid"),
                command="cmd1",
            ),
        ]
        with pytest.raises(ValueError, match="invalid regex pattern"):
            TriggerManager(configs)

    @pytest.mark.asyncio
    async def test_on_gcode_received_no_match(self):
        """Test on_gcode_received when no trigger matches."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="cmd1",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_received("G28", ("127.0.0.1", 1234))
        assert result == "G28"
        assert len(manager._pending_tasks) == 0

    @pytest.mark.asyncio
    async def test_on_gcode_received_with_match(self):
        """Test on_gcode_received when trigger matches."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_received("M8", ("127.0.0.1", 1234))
        assert result == "M8"
        assert len(manager._pending_tasks) == 1
        
        # Wait for the task to complete
        await asyncio.sleep(0.1)
        assert len(manager._pending_tasks) == 0

    @pytest.mark.asyncio
    async def test_on_gcode_received_multiple_matches(self):
        """Test on_gcode_received with multiple matching triggers."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="trigger2",
                trigger=GCodeTriggerConfig(type="gcode", match="M[89]"),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_received("M8", ("127.0.0.1", 1234))
        assert result == "M8"
        # Both triggers should match M8
        assert len(manager._pending_tasks) == 2
        
        # Wait for tasks to complete
        await asyncio.sleep(0.1)
        assert len(manager._pending_tasks) == 0

    @pytest.mark.asyncio
    async def test_on_gcode_sent(self):
        """Test on_gcode_sent is a no-op."""
        manager = TriggerManager()
        # Should not raise any exceptions
        await manager.on_gcode_sent("M8", ("127.0.0.1", 1234))

    @pytest.mark.asyncio
    async def test_shutdown_with_no_pending_tasks(self):
        """Test shutdown with no pending tasks."""
        manager = TriggerManager()
        # Should not raise any exceptions
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_tasks(self):
        """Test shutdown waits for pending tasks."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="sleep 0.1 && exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        # Trigger a command
        await manager.on_gcode_received("M8", ("127.0.0.1", 1234))
        assert len(manager._pending_tasks) == 1
        
        # Shutdown should wait for task
        await manager.shutdown()
        assert len(manager._pending_tasks) == 0


class TestTriggerConfigRoundtrip:
    """Tests for trigger configuration save/load roundtrip."""

    def test_trigger_to_dict(self):
        """Test converting trigger config to dictionary."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="script.py",
        )
        data = {
            "id": config.id,
            "trigger": {"type": config.trigger.type, "match": config.trigger.match},
            "command": config.command,
        }
        assert data["id"] == "test"
        assert data["trigger"]["type"] == "gcode"
        assert data["trigger"]["match"] == "M8"
        assert data["command"] == "script.py"

    def test_trigger_roundtrip(self):
        """Test saving and loading a trigger config."""
        original = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="script.py",
        )
        
        # Convert to dict
        data = {
            "id": original.id,
            "trigger": {
                "type": original.trigger.type,
                "match": original.trigger.match,
            },
            "command": original.command,
        }
        
        # Load from dict
        loaded = CustomTriggerConfig.from_dict(data)
        
        assert loaded.id == original.id
        assert loaded.trigger.type == original.trigger.type
        assert loaded.trigger.match == original.trigger.match
        assert loaded.command == original.command
