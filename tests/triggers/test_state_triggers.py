"""Tests for state trigger functionality."""

import asyncio
import pytest

from src.gcode_proxy.trigger.triggers_config import (
    CustomTriggerConfig,
    StateTriggerConfig,
    GCodeTriggerConfig,
)
from src.gcode_proxy.trigger.trigger import StateTrigger, Trigger
from src.gcode_proxy.trigger.trigger_manager import TriggerManager


class TestStateTriggerConfig:
    """Tests for StateTriggerConfig dataclass."""

    def test_state_trigger_config_creation(self):
        """Test creating a StateTriggerConfig."""
        config = StateTriggerConfig(
            type="state",
            match="Idle",
            delay=5.0
        )
        assert config.type == "state"
        assert config.match == "Idle"
        assert config.delay == 5.0

    def test_state_trigger_config_default_delay(self):
        """Test that StateTriggerConfig has default delay of 0."""
        config = StateTriggerConfig(
            type="state",
            match="Idle"
        )
        assert config.delay == 0

    def test_state_trigger_config_from_dict(self):
        """Test creating StateTriggerConfig from dictionary."""
        data = {
            "type": "state",
            "match": "Idle",
            "delay": 10
        }
        config = StateTriggerConfig.from_dict(data)
        assert config.type == "state"
        assert config.match == "Idle"
        assert config.delay == 10.0

    def test_state_trigger_config_missing_type(self):
        """Test that missing type raises ValueError."""
        data = {
            "match": "Idle",
            "delay": 10
        }
        with pytest.raises(ValueError, match="'type' is required"):
            StateTriggerConfig.from_dict(data)

    def test_state_trigger_config_missing_match(self):
        """Test that missing match raises ValueError."""
        data = {
            "type": "state",
            "delay": 10
        }
        with pytest.raises(ValueError, match="'match' pattern is required"):
            StateTriggerConfig.from_dict(data)

    def test_state_trigger_config_invalid_type(self):
        """Test that invalid type raises ValueError."""
        data = {
            "type": "invalid",
            "match": "Idle"
        }
        with pytest.raises(ValueError, match="Unsupported trigger type"):
            StateTriggerConfig.from_dict(data)

    def test_state_trigger_config_negative_delay(self):
        """Test that negative delay raises ValueError."""
        data = {
            "type": "state",
            "match": "Idle",
            "delay": -5
        }
        with pytest.raises(ValueError, match="must be non-negative"):
            StateTriggerConfig.from_dict(data)

    def test_state_trigger_config_invalid_delay(self):
        """Test that invalid delay raises ValueError."""
        data = {
            "type": "state",
            "match": "Idle",
            "delay": "not-a-number"
        }
        with pytest.raises(ValueError, match="Invalid delay value"):
            StateTriggerConfig.from_dict(data)


class TestStateTrigger:
    """Tests for StateTrigger class."""

    def test_state_trigger_creation(self):
        """Test creating a StateTrigger."""
        config = CustomTriggerConfig(
            id="idle-power-off",
            trigger=StateTriggerConfig(
                type="state",
                match="Idle",
                delay=5.0
            ),
            command="echo 'Power off'"
        )
        trigger = StateTrigger(config)
        assert trigger.id == "idle-power-off"
        assert trigger.command == "echo 'Power off'"
        assert trigger.delay == 5.0

    def test_state_trigger_matches_exact(self):
        """Test that state trigger matches exact state."""
        config = CustomTriggerConfig(
            id="idle-trigger",
            trigger=StateTriggerConfig(
                type="state",
                match="Idle"
            ),
            command="echo 'Idle'"
        )
        trigger = StateTrigger(config)
        assert trigger.matches("Idle")

    def test_state_trigger_matches_with_whitespace(self):
        """Test that state trigger matches with whitespace."""
        config = CustomTriggerConfig(
            id="idle-trigger",
            trigger=StateTriggerConfig(
                type="state",
                match="Idle"
            ),
            command="echo 'Idle'"
        )
        trigger = StateTrigger(config)
        assert trigger.matches("  Idle  ")

    def test_state_trigger_matches_regex(self):
        """Test that state trigger matches regex patterns."""
        config = CustomTriggerConfig(
            id="idle-or-run",
            trigger=StateTriggerConfig(
                type="state",
                match="Idle|Run"
            ),
            command="echo 'Idle or Run'"
        )
        trigger = StateTrigger(config)
        assert trigger.matches("Idle")
        assert trigger.matches("Run")
        assert not trigger.matches("Hold")

    def test_state_trigger_invalid_regex(self):
        """Test that invalid regex raises ValueError."""
        config = CustomTriggerConfig(
            id="bad-regex",
            trigger=StateTriggerConfig(
                type="state",
                match="[invalid("
            ),
            command="echo 'test'"
        )
        with pytest.raises(ValueError, match="invalid regex pattern"):
            StateTrigger(config)

    def test_state_trigger_wrong_config_type(self):
        """Test that wrong config type raises ValueError."""
        config = CustomTriggerConfig(
            id="wrong-type",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8"
            ),
            command="echo 'test'"
        )
        with pytest.raises(ValueError, match="must have a StateTriggerConfig"):
            StateTrigger(config)


class TestCustomTriggerConfigWithState:
    """Tests for CustomTriggerConfig with state triggers."""

    def test_custom_trigger_from_dict_state(self):
        """Test creating CustomTriggerConfig from dict with state trigger."""
        data = {
            "id": "idle-power-off",
            "trigger": {
                "type": "state",
                "match": "Idle",
                "delay": 300
            },
            "command": "hass-cli service call homeassistant.turn_off"
        }
        config = CustomTriggerConfig.from_dict(data)
        assert config.id == "idle-power-off"
        assert isinstance(config.trigger, StateTriggerConfig)
        assert config.trigger.match == "Idle"
        assert config.trigger.delay == 300
        assert config.command == "hass-cli service call homeassistant.turn_off"

    def test_custom_trigger_from_dict_gcode(self):
        """Test that CustomTriggerConfig still works with gcode triggers."""
        data = {
            "id": "air-assist",
            "trigger": {
                "type": "gcode",
                "match": "M8",
                "synchronize": False
            },
            "command": "echo 'Air assist on'"
        }
        config = CustomTriggerConfig.from_dict(data)
        assert config.id == "air-assist"
        assert isinstance(config.trigger, GCodeTriggerConfig)
        assert config.trigger.match == "M8"


class TestTriggerManager:
    """Tests for TriggerManager with state triggers."""

    def setup_method(self):
        """Reset TriggerManager before each test."""
        TriggerManager.reset()

    def test_load_state_triggers(self):
        """Test loading state triggers."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-power-off",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 300
                },
                "command": "echo 'Power off'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        assert len(manager.state_triggers) == 1
        assert manager.state_triggers[0].id == "idle-power-off"

    def test_find_matching_state_triggers(self):
        """Test finding matching state triggers."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle"
                },
                "command": "echo 'Idle'"
            }),
            CustomTriggerConfig.from_dict({
                "id": "run-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Run"
                },
                "command": "echo 'Run'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        idle_triggers = manager.find_matching_state_triggers("Idle")
        assert len(idle_triggers) == 1
        assert idle_triggers[0].id == "idle-trigger"
        
        run_triggers = manager.find_matching_state_triggers("Run")
        assert len(run_triggers) == 1
        assert run_triggers[0].id == "run-trigger"

    def test_find_no_matching_state_triggers(self):
        """Test when no state triggers match."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle"
                },
                "command": "echo 'Idle'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        hold_triggers = manager.find_matching_state_triggers("Hold")
        assert len(hold_triggers) == 0

    def test_gcode_and_state_triggers_together(self):
        """Test loading both gcode and state triggers."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "air-assist-on",
                "trigger": {
                    "type": "gcode",
                    "match": "M8"
                },
                "command": "echo 'Air on'"
            }),
            CustomTriggerConfig.from_dict({
                "id": "idle-power-off",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 300
                },
                "command": "echo 'Power off'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        assert len(manager.gcode_triggers) == 1
        assert len(manager.state_triggers) == 1

    @pytest.mark.asyncio
    async def test_on_device_status_executes_triggers(self):
        """Test that on_device_status executes matching triggers."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0  # No delay for testing
                },
                "command": "true"  # Use 'true' command that always succeeds
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Execute on_device_status
        await manager.on_device_status("Idle")
        
        # Give background tasks a moment to complete
        await asyncio.sleep(0.1)
        
        # Check that background task was created and cleaned up
        assert len(manager._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_on_device_status_with_delay(self):
        """Test that on_device_status respects delay."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "delayed-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.05  # 50ms delay
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        import time
        start_time = time.time()
        
        # Execute on_device_status
        await manager.on_device_status("Idle")
        
        # Wait for trigger to complete
        await asyncio.sleep(0.1)
        
        elapsed_time = time.time() - start_time
        
        # Should take at least the delay time
        assert elapsed_time >= 0.05

    @pytest.mark.asyncio
    async def test_pending_task_cleanup(self):
        """Test that pending state trigger tasks are cleaned up after completion."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "cleanup-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle"
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Execute on_device_status
        await manager.on_device_status("Idle")
        
        # Task should be pending
        assert len(manager._pending_state_triggers) == 1
        assert "cleanup-trigger" in manager._pending_state_triggers
        
        # Wait for task to complete
        await asyncio.sleep(0.2)
        
        # After completion, pending task should be cleaned up
        assert len(manager._pending_state_triggers) == 0

    @pytest.mark.asyncio
    async def test_state_trigger_consistency_cancellation(self):
        """Test that triggers are cancelled if state changes and no longer matches."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-power-off",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.5  # 500ms delay
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger on Idle state
        await manager.on_device_status("Idle")
        assert "idle-power-off" in manager._pending_state_triggers
        
        # Change state to Run (doesn't match "Idle" pattern)
        await asyncio.sleep(0.1)  # Wait 100ms
        await manager.on_device_status("Run")
        
        # Trigger should be cancelled
        assert "idle-power-off" not in manager._pending_state_triggers
        
        # Wait to ensure no late execution
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    async def test_state_trigger_consistency_preserved(self):
        """Test that triggers execute if state remains consistent."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-power-off",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.1  # 100ms delay
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger on Idle state
        await manager.on_device_status("Idle")
        assert "idle-power-off" in manager._pending_state_triggers
        
        # State remains Idle
        await asyncio.sleep(0.05)
        await manager.on_device_status("Idle")
        
        # Task should still be pending (or completed after delay)
        # Wait for completion
        await asyncio.sleep(0.2)
        
        # Task should be cleaned up after execution
        assert "idle-power-off" not in manager._pending_state_triggers

    @pytest.mark.asyncio
    async def test_state_trigger_singularity_replacement(self):
        """Test that multiple triggers with same ID replace each other."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.2  # 200ms delay
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger first time
        await manager.on_device_status("Idle")
        first_task = manager._pending_state_triggers.get("idle-trigger")
        assert first_task is not None
        
        # Wait a bit
        await asyncio.sleep(0.05)
        
        # Trigger again (should replace the previous one)
        await manager.on_device_status("Idle")
        second_task = manager._pending_state_triggers.get("idle-trigger")
        
        # Should be a different task
        assert second_task is not None
        assert second_task is not first_task or first_task.cancelled()
        
        # Wait for completion
        await asyncio.sleep(0.3)
        
        # Trigger should be cleaned up
        assert "idle-trigger" not in manager._pending_state_triggers

    @pytest.mark.asyncio
    async def test_state_trigger_regex_consistency(self):
        """Test consistency checking with regex patterns."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-or-hold",
                "trigger": {
                    "type": "state",
                    "match": "Idle|Hold",
                    "delay": 0.3  # 300ms delay
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger on Hold state
        await manager.on_device_status("Hold")
        assert "idle-or-hold" in manager._pending_state_triggers
        
        # Change to state that doesn't match
        await asyncio.sleep(0.05)
        await manager.on_device_status("Run")
        
        # Trigger should be cancelled
        assert "idle-or-hold" not in manager._pending_state_triggers
        
        # Trigger again on Idle (matches pattern)
        await manager.on_device_status("Idle")
        assert "idle-or-hold" in manager._pending_state_triggers
        
        # Wait for execution
        await asyncio.sleep(0.4)
        
        # Should be cleaned up
        assert "idle-or-hold" not in manager._pending_state_triggers

    @pytest.mark.asyncio
    async def test_multiple_different_triggers_singularity(self):
        """Test that different triggers have independent singularity."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "trigger-1",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.1
                },
                "command": "true"
            }),
            CustomTriggerConfig.from_dict({
                "id": "trigger-2",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 0.1
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger both on Idle
        await manager.on_device_status("Idle")
        assert len(manager._pending_state_triggers) == 2
        assert "trigger-1" in manager._pending_state_triggers
        assert "trigger-2" in manager._pending_state_triggers
        
        # Different task objects
        task1 = manager._pending_state_triggers["trigger-1"]
        task2 = manager._pending_state_triggers["trigger-2"]
        assert task1 is not task2
        
        # Wait for completion
        await asyncio.sleep(0.2)
        
        # Both should be cleaned up
        assert len(manager._pending_state_triggers) == 0

    @pytest.mark.asyncio
    async def test_trigger_cancellation_on_state_change(self):
        """Test that pending trigger is cancelled when state changes."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "idle-trigger",
                "trigger": {
                    "type": "state",
                    "match": "Idle",
                    "delay": 1.0  # 1 second delay (long enough to observe cancellation)
                },
                "command": "true"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Trigger on Idle
        await manager.on_device_status("Idle")
        task = manager._pending_state_triggers["idle-trigger"]
        
        # Immediately change state
        await manager.on_device_status("Run")
        
        # Task should be cancelled
        assert task.cancelled()
        assert "idle-trigger" not in manager._pending_state_triggers


class TestGCodeTriggerConfig:
    """Tests for GCodeTriggerConfig with state restrictions."""

    def test_gcode_trigger_config_without_state(self):
        """Test GCodeTriggerConfig without state restriction."""
        config = GCodeTriggerConfig(
            type="gcode",
            match="M8",
            synchronize=False
        )
        assert config.type == "gcode"
        assert config.match == "M8"
        assert config.state is None

    def test_gcode_trigger_config_with_state(self):
        """Test GCodeTriggerConfig with state restriction."""
        config = GCodeTriggerConfig(
            type="gcode",
            match="M8",
            state="Idle"
        )
        assert config.type == "gcode"
        assert config.match == "M8"
        assert config.state == "Idle"

    def test_gcode_trigger_config_from_dict_with_state(self):
        """Test creating GCodeTriggerConfig from dict with state."""
        data = {
            "type": "gcode",
            "match": "M8",
            "state": "Idle"
        }
        config = GCodeTriggerConfig.from_dict(data)
        assert config.state == "Idle"

    def test_gcode_trigger_config_from_dict_without_state(self):
        """Test creating GCodeTriggerConfig from dict without state."""
        data = {
            "type": "gcode",
            "match": "M8"
        }
        config = GCodeTriggerConfig.from_dict(data)
        assert config.state is None

    def test_gcode_trigger_config_state_stripped(self):
        """Test that state is stripped of whitespace."""
        data = {
            "type": "gcode",
            "match": "M8",
            "state": "  Idle  "
        }
        config = GCodeTriggerConfig.from_dict(data)
        assert config.state == "Idle"


class TestTriggerWithStateRestriction:
    """Tests for Trigger class with state restrictions."""

    def test_trigger_matches_without_state_restriction(self):
        """Test that trigger without state restriction matches any state."""
        config = CustomTriggerConfig(
            id="air-on",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8",
                state=None
            ),
            command="echo 'Air on'"
        )
        trigger = Trigger(config)
        
        assert trigger.matches("M8")
        assert trigger.matches("M8", "Idle")
        assert trigger.matches("M8", "Run")
        assert trigger.matches("M8", "Hold")

    def test_trigger_matches_with_state_restriction(self):
        """Test that trigger with state restriction only matches in that state."""
        config = CustomTriggerConfig(
            id="air-on",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8",
                state="Idle"
            ),
            command="echo 'Air on'"
        )
        trigger = Trigger(config)
        
        # Matches only when state is "Idle"
        assert trigger.matches("M8", "Idle")
        
        # Doesn't match in other states
        assert not trigger.matches("M8", "Run")
        assert not trigger.matches("M8", "Hold")
        assert not trigger.matches("M8", None)

    def test_trigger_state_restriction_with_whitespace(self):
        """Test that state comparison handles whitespace."""
        config = CustomTriggerConfig(
            id="air-on",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8",
                state="Idle"
            ),
            command="echo 'Air on'"
        )
        trigger = Trigger(config)
        
        # Should match even with whitespace (stripped in matches())
        assert trigger.matches("M8", "  Idle  ")

    def test_trigger_gcode_match_with_state_restriction(self):
        """Test that both GCode and state must match."""
        config = CustomTriggerConfig(
            id="air-on",
            trigger=GCodeTriggerConfig(
                type="gcode",
                match="M8",
                state="Idle"
            ),
            command="echo 'Air on'"
        )
        trigger = Trigger(config)
        
        # GCode must match
        assert trigger.matches("M8", "Idle")
        assert not trigger.matches("M9", "Idle")  # Wrong GCode
        assert not trigger.matches("M8", "Run")   # Wrong state


class TestTriggerManagerWithStateRestrictions:
    """Tests for TriggerManager with state-restricted GCode triggers."""

    def setup_method(self):
        """Reset TriggerManager before each test."""
        TriggerManager.reset()

    def test_trigger_manager_tracks_current_state(self):
        """Test that TriggerManager tracks current device state."""
        manager = TriggerManager.get_instance()
        assert manager._current_device_state is None
        
        manager.set_current_device_state("Idle")
        assert manager._current_device_state == "Idle"
        
        manager.set_current_device_state("Run")
        assert manager._current_device_state == "Run"

    def test_find_gcode_triggers_respects_state_restriction(self):
        """Test that find_matching_gcode_triggers respects state restrictions."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "air-on-idle",
                "trigger": {
                    "type": "gcode",
                    "match": "M8",
                    "state": "Idle"
                },
                "command": "echo 'Air on'"
            }),
            CustomTriggerConfig.from_dict({
                "id": "air-on-any",
                "trigger": {
                    "type": "gcode",
                    "match": "M8"
                },
                "command": "echo 'Air on'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # When in Idle state, both triggers match
        manager.set_current_device_state("Idle")
        matching = manager.find_matching_gcode_triggers("M8")
        assert len(matching) == 2
        
        # When in Run state, only the unrestricted trigger matches
        manager.set_current_device_state("Run")
        matching = manager.find_matching_gcode_triggers("M8")
        assert len(matching) == 1
        assert matching[0].id == "air-on-any"

    def test_build_tasks_with_state_restriction(self):
        """Test that build_tasks_for_gcode respects state restrictions."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "air-on",
                "trigger": {
                    "type": "gcode",
                    "match": "M8",
                    "state": "Idle"
                },
                "command": "echo 'Air on'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # When in Idle state, trigger matches
        manager.set_current_device_state("Idle")
        tasks = manager.build_tasks_for_gcode("M8", "client-uuid")
        assert tasks is not None
        assert len(tasks) == 1
        
        # When in Run state, trigger doesn't match
        manager.set_current_device_state("Run")
        tasks = manager.build_tasks_for_gcode("M8", "client-uuid")
        assert tasks is None

    def test_state_restriction_with_regex_pattern(self):
        """Test state restriction combined with regex GCode patterns."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "power-on",
                "trigger": {
                    "type": "gcode",
                    "match": ".*",
                    "state": "Disconnected"
                },
                "command": "echo 'Power on'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Should only match when in Disconnected state
        manager.set_current_device_state("Disconnected")
        matching = manager.find_matching_gcode_triggers("G0")
        assert len(matching) == 1
        
        manager.set_current_device_state("Idle")
        matching = manager.find_matching_gcode_triggers("G0")
        assert len(matching) == 0

    async def test_state_restriction_during_device_status_update(self):
        """Test that state is updated during on_device_status call."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "air-on",
                "trigger": {
                    "type": "gcode",
                    "match": "M8",
                    "state": "Idle"
                },
                "command": "echo 'Air on'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # Initially no state
        assert manager._current_device_state is None
        
        # After state update, state should be set
        await manager.on_device_status("Idle")
        assert manager._current_device_state == "Idle"
        
        # After another update
        await manager.on_device_status("Run")
        assert manager._current_device_state == "Run"

    def test_multiple_state_restrictions(self):
        """Test multiple GCode triggers with different state restrictions."""
        configs = [
            CustomTriggerConfig.from_dict({
                "id": "air-on-idle",
                "trigger": {
                    "type": "gcode",
                    "match": "M8",
                    "state": "Idle"
                },
                "command": "echo 'Air on'"
            }),
            CustomTriggerConfig.from_dict({
                "id": "air-on-run",
                "trigger": {
                    "type": "gcode",
                    "match": "M8",
                    "state": "Run"
                },
                "command": "echo 'Air on while running'"
            }),
            CustomTriggerConfig.from_dict({
                "id": "air-on-always",
                "trigger": {
                    "type": "gcode",
                    "match": "M8"
                },
                "command": "echo 'Air on (no restriction)'"
            })
        ]
        manager = TriggerManager.get_instance()
        manager.load_from_config(configs)
        
        # In Idle state
        manager.set_current_device_state("Idle")
        matching = manager.find_matching_gcode_triggers("M8")
        assert len(matching) == 2  # idle and always
        assert set(t.id for t in matching) == {"air-on-idle", "air-on-always"}
        
        # In Run state
        manager.set_current_device_state("Run")
        matching = manager.find_matching_gcode_triggers("M8")
        assert len(matching) == 2  # run and always
        assert set(t.id for t in matching) == {"air-on-run", "air-on-always"}
        
        # In Hold state
        manager.set_current_device_state("Hold")
        matching = manager.find_matching_gcode_triggers("M8")
        assert len(matching) == 1  # only always
        assert matching[0].id == "air-on-always"