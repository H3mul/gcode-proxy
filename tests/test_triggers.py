"""Tests for trigger matching and execution."""

import pytest

from src.gcode_proxy.trigger import Trigger
from src.gcode_proxy.trigger_manager import TriggerManager
from src.gcode_proxy.triggers_config import (
    CustomTriggerConfig,
    GCodeTriggerConfig,
    TriggerBehavior,
)
from src.gcode_proxy.handlers import GCodeHandlerPreResponse


class TestGCodeTriggerConfig:
    """Tests for GCodeTriggerConfig."""

    def test_create_from_dict_valid(self):
        """Test creating a valid GCode trigger config."""
        config = GCodeTriggerConfig.from_dict({
            "type": "gcode",
            "match": "M8",
        })
        assert config.type == "gcode"
        assert config.match == "M8"
        assert config.behavior == TriggerBehavior.CAPTURE
        assert config.synchronize is False

    def test_create_from_dict_with_synchronize(self):
        """Test creating a GCode trigger config with synchronize flag."""
        config = GCodeTriggerConfig.from_dict({
            "type": "gcode",
            "match": "M9",
            "synchronize": True,
        })
        assert config.synchronize is True

    def test_create_from_dict_synchronize_false_explicit(self):
        """Test creating a GCode trigger config with explicit synchronize=False."""
        config = GCodeTriggerConfig.from_dict({
            "type": "gcode",
            "match": "M8",
            "synchronize": False,
        })
        assert config.synchronize is False

    def test_create_from_dict_synchronize_defaults_false(self):
        """Test that synchronize defaults to False."""
        config = GCodeTriggerConfig.from_dict({
            "type": "gcode",
            "match": "M8",
        })
        assert config.synchronize is False

    def test_create_from_dict_missing_type(self):
        """Test that missing type raises ValueError."""
        with pytest.raises(ValueError):
            GCodeTriggerConfig.from_dict({"match": "M8"})

    def test_create_from_dict_missing_match(self):
        """Test that missing match raises ValueError."""
        with pytest.raises(ValueError):
            GCodeTriggerConfig.from_dict({"type": "gcode"})

    def test_create_from_dict_empty_type(self):
        """Test that empty type raises ValueError."""
        with pytest.raises(ValueError):
            GCodeTriggerConfig.from_dict({"type": "", "match": "M8"})

    def test_create_from_dict_unsupported_type(self):
        """Test that unsupported type raises ValueError."""
        with pytest.raises(ValueError):
            GCodeTriggerConfig.from_dict({"type": "unknown", "match": "M8"})


class TestCustomTriggerConfig:
    """Tests for CustomTriggerConfig."""

    def test_create_from_dict_valid(self):
        """Test creating a valid custom trigger config."""
        config = CustomTriggerConfig.from_dict({
            "id": "test-trigger",
            "trigger": {
                "type": "gcode",
                "match": "M8",
            },
            "command": "exit 0",
        })
        assert config.id == "test-trigger"
        assert config.trigger.match == "M8"
        assert config.command == "exit 0"

    def test_create_from_dict_valid_with_synchronize(self):
        """Test creating a valid custom trigger config with synchronize flag."""
        config = CustomTriggerConfig.from_dict({
            "id": "test-trigger",
            "trigger": {
                "type": "gcode",
                "match": "M9",
                "synchronize": True,
            },
            "command": "exit 0",
        })
        assert config.trigger.synchronize is True

    def test_create_from_dict_valid_2(self):
        """Test creating a valid custom trigger config."""
        config = CustomTriggerConfig.from_dict({
            "id": "test-trigger",
            "trigger": {
                "type": "gcode",
                "match": "M8",
            },
            "command": "exit 0",
        })
        assert config.id == "test-trigger"
        assert config.trigger.match == "M8"
        assert config.command == "exit 0"

    def test_create_from_dict_missing_id(self):
        """Test that missing id raises ValueError."""
        with pytest.raises(ValueError):
            CustomTriggerConfig.from_dict({
                "trigger": {"type": "gcode", "match": "M8"},
                "command": "exit 0",
            })

    def test_create_from_dict_missing_trigger(self):
        """Test that missing trigger raises ValueError."""
        with pytest.raises(ValueError):
            CustomTriggerConfig.from_dict({
                "id": "test-trigger",
                "command": "exit 0",
            })

    def test_create_from_dict_missing_command(self):
        """Test that missing command raises ValueError."""
        with pytest.raises(ValueError):
            CustomTriggerConfig.from_dict({
                "id": "test-trigger",
                "trigger": {"type": "gcode", "match": "M8"},
            })

    def test_create_from_dict_invalid_trigger(self):
        """Test that invalid trigger config raises ValueError."""
        with pytest.raises(ValueError):
            CustomTriggerConfig.from_dict({
                "id": "test-trigger",
                "trigger": {"type": "unknown", "match": "M8"},
                "command": "exit 0",
            })


class TestTrigger:
    """Tests for Trigger class."""

    def test_init_valid(self):
        """Test initializing a valid trigger."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.id == "test"
        assert trigger.command == "exit 0"
        assert trigger.behavior == TriggerBehavior.CAPTURE
        assert trigger.synchronize is False

    def test_init_with_synchronize(self):
        """Test initializing a trigger with synchronize flag."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M9",
                synchronize=True,
            ),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.synchronize is True

    def test_init_invalid_regex(self):
        """Test that invalid regex raises ValueError."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="[invalid(regex"),
            command="exit 0",
        )
        
        with pytest.raises(ValueError) as exc_info:
            Trigger(config)
        assert "invalid regex pattern" in str(exc_info.value)

    def test_matches_exact(self):
        """Test matching an exact GCode command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="G28"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.matches("G28") is True
        assert trigger.matches("G28 X Y Z") is True
        assert trigger.matches("G29") is False

    def test_matches_case_sensitive(self):
        """Test that matching is case-sensitive by default."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M104"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.matches("M104") is True
        # Regex pattern "M104" won't match lowercase
        assert trigger.matches("m104") is False

    def test_matches_regex_pattern(self):
        """Test matching with regex patterns."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M[89]"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.matches("M8") is True
        assert trigger.matches("M9") is True
        assert trigger.matches("M7") is False

    def test_matches_partial(self):
        """Test that regex matches partial strings."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="G1 X"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        assert trigger.matches("G1 X10 Y20") is True
        assert trigger.matches("G1 Z5") is False

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful trigger execution."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="exit 0",
        )
        trigger = Trigger(config)
        
        success, error = await trigger.execute()
        assert success is True
        assert error is None

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """Test failed trigger execution."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="exit 1",
        )
        trigger = Trigger(config)
        
        success, error = await trigger.execute()
        assert success is False
        assert error is not None

    @pytest.mark.asyncio
    async def test_execute_nonexistent_command(self):
        """Test execution of nonexistent command."""
        config = CustomTriggerConfig(
            id="test",
            trigger=GCodeTriggerConfig(type="gcode", match="M8"),
            command="/nonexistent/command/that/does/not/exist",
        )
        trigger = Trigger(config)
        
        success, error = await trigger.execute()
        assert success is False
        assert error is not None


class TestTriggerManager:
    """Tests for TriggerManager class."""

    def test_init_empty(self):
        """Test initializing an empty trigger manager."""
        manager = TriggerManager()
        assert manager.triggers == []

    def test_init_with_triggers(self):
        """Test initializing trigger manager with triggers."""
        configs = [
            CustomTriggerConfig(
                id="trigger1",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="trigger2",
                trigger=GCodeTriggerConfig(type="gcode", match="M9"),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        assert len(manager.triggers) == 2
        assert manager.triggers[0].id == "trigger1"
        assert manager.triggers[1].id == "trigger2"

    def test_init_with_invalid_trigger(self):
        """Test that invalid trigger raises during initialization."""
        configs = [
            CustomTriggerConfig(
                id="invalid",
                trigger=GCodeTriggerConfig(type="gcode", match="[invalid(regex"),
                command="exit 0",
            ),
        ]
        
        with pytest.raises(ValueError):
            TriggerManager(configs)

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_match_capture(self):
        """Test on_gcode_pre executes pre-phase triggers with CAPTURE behavior."""
        configs = [
            CustomTriggerConfig(
                id="pre-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        assert result is not None
        assert isinstance(result, GCodeHandlerPreResponse)
        assert result.should_forward is False
        assert result.fake_response == "ok"
        assert result.should_synchronize is False

    @pytest.mark.asyncio
    async def test_on_gcode_pre_no_match(self):
        """Test on_gcode_pre when no triggers match."""
        configs = [
            CustomTriggerConfig(
                id="trigger",
                trigger=GCodeTriggerConfig(type="gcode", match="M8"),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("G28", ("127.0.0.1", 1234))
        
        assert result is not None
        assert result.should_forward is True
        assert result.fake_response is None
        assert result.should_synchronize is False

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_match_forward(self):
        """Test on_gcode_pre with FORWARD behavior trigger."""
        configs = [
            CustomTriggerConfig(
                id="forward-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.FORWARD,
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        assert result is not None
        assert result.should_forward is True
        assert result.fake_response is None
        assert result.should_synchronize is False

    @pytest.mark.asyncio
    async def test_on_gcode_pre_multiple_triggers_mixed_behavior(self):
        """Test on_gcode_pre with multiple triggers of different behaviors."""
        configs = [
            CustomTriggerConfig(
                id="capture-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="forward-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.FORWARD,
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        # When ANY trigger is FORWARD, should_forward is True
        assert result is not None
        assert result.should_forward is True
        assert result.fake_response is None

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_capture_nowait(self):
        """Test on_gcode_pre with CAPTURE_NOWAIT behavior."""
        configs = [
            CustomTriggerConfig(
                id="nowait-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE_NOWAIT,
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        assert result is not None
        # CAPTURE_NOWAIT doesn't wait, returns success immediately
        assert result.should_forward is False
        assert result.fake_response == "ok"

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_sync_triggers(self):
        """Test on_gcode_pre defers triggers with synchronize flag."""
        configs = [
            CustomTriggerConfig(
                id="sync-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        assert result is not None
        # Sync triggers are deferred, so should_forward is True
        assert result.should_forward is True
        assert result.fake_response is None
        assert result.should_synchronize is True

    @pytest.mark.asyncio
    async def test_on_gcode_pre_mixed_sync_and_non_sync(self):
        """Test on_gcode_pre with both sync and non-sync triggers."""
        configs = [
            CustomTriggerConfig(
                id="pre-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="post-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        # Pre-trigger executes and returns ok, but we need to sync for post-trigger
        assert result is not None
        assert result.should_synchronize is True

    @pytest.mark.asyncio
    async def test_on_gcode_post_executes_sync_triggers(self):
        """Test on_gcode_post executes deferred sync triggers."""
        configs = [
            CustomTriggerConfig(
                id="post-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        # Execute post-phase
        result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234))
        
        # Should return None since there are no pre-triggers
        # Post-phase handles the result internally
        assert result is None

    @pytest.mark.asyncio
    async def test_on_gcode_post_no_matching_triggers(self):
        """Test on_gcode_post when no post-triggers match."""
        configs = [
            CustomTriggerConfig(
                id="trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_post("G28", ("127.0.0.1", 1234))
        
        assert result is None

    @pytest.mark.asyncio
    async def test_shutdown_with_no_pending_tasks(self):
        """Test shutdown completes immediately with no pending tasks."""
        manager = TriggerManager()
        
        # Should not raise
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_tasks(self):
        """Test shutdown waits for pending trigger tasks."""
        configs = [
            CustomTriggerConfig(
                id="nowait-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE_NOWAIT,
                    synchronize=False,
                ),
                command="sleep 0.1 && exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        # Trigger a CAPTURE_NOWAIT which spawns a background task
        await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        # Should have pending tasks
        assert len(manager._pending_tasks) > 0
        
        # Shutdown should wait for them
        await manager.shutdown()
        
        # No more pending tasks
        assert len(manager._pending_tasks) == 0


class TestTriggerConfigRoundtrip:
    """Tests for trigger config serialization and deserialization."""

    def test_trigger_dict_construction(self):
        """Test constructing a trigger config from dict representation."""
        trigger_dict = {
            "id": "test",
            "trigger": {
                "type": "gcode",
                "match": "M8",
                "behavior": "capture",
                "synchronize": False,
            },
            "command": "exit 0",
        }
        
        config = CustomTriggerConfig.from_dict(trigger_dict)
        
        assert config.id == "test"
        assert config.trigger.type == "gcode"
        assert config.trigger.match == "M8"
        assert config.command == "exit 0"

    def test_trigger_roundtrip(self):
        """Test roundtrip serialization and deserialization."""
        # Create a trigger config
        original = CustomTriggerConfig(
            id="test-trigger",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M[89]",
                behavior=TriggerBehavior.FORWARD,
                synchronize=True,
            ),
            command="some command",
        )
        
        # Manually construct dict representation
        as_dict = {
            "id": original.id,
            "trigger": {
                "type": original.trigger.type,
                "match": original.trigger.match,
                "behavior": original.trigger.behavior.value,
                "synchronize": original.trigger.synchronize,
            },
            "command": original.command,
        }
        
        # Deserialize back
        restored = CustomTriggerConfig.from_dict(as_dict)
        
        assert restored.id == original.id
        assert restored.trigger.type == original.trigger.type
        assert restored.trigger.match == original.trigger.match
        assert restored.trigger.behavior == original.trigger.behavior
        assert restored.trigger.synchronize == original.trigger.synchronize
        assert restored.command == original.command