"""Tests for two-stage trigger handling with synchronization.

Tests verify that triggers are executed in the correct phase:
- Pre-phase (on_gcode_pre): Triggers without synchronize flag
- Post-phase (on_gcode_post): Triggers with synchronize flag, after G4 P0
"""

import asyncio
import pytest

from src.gcode_proxy.handlers import GCodeHandlerPreResponse
from src.gcode_proxy.trigger_manager import TriggerManager
from src.gcode_proxy.triggers_config import (
    CustomTriggerConfig,
    GCodeTriggerConfig,
    TriggerBehavior,
)


class TestTwoStageTriggerHandling:
    """Tests for two-stage trigger execution with synchronization."""

    @pytest.mark.asyncio
    async def test_on_gcode_pre_executes_non_sync_triggers(self):
        """Test that on_gcode_pre executes triggers without synchronize flag."""
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
    async def test_on_gcode_pre_defers_sync_triggers(self):
        """Test that on_gcode_pre defers triggers with synchronize flag."""
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
        
        result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        assert result is not None
        assert result.should_forward is True
        assert result.should_synchronize is True
        # Pre-phase should not execute the post-trigger
        assert result.fake_response is None

    @pytest.mark.asyncio
    async def test_on_gcode_post_executes_sync_triggers(self):
        """Test that on_gcode_post executes deferred sync triggers."""
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
        
        # Call post-phase
        result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234))
        
        # Post-phase returns None (results handled internally)
        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_pre_and_post_triggers(self):
        """Test handling of both pre and post triggers together."""
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
        
        # Pre-phase: M9 matches both, but only pre-trigger is executed
        pre_result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        assert pre_result is not None
        assert pre_result.should_synchronize is True
        # Pre-trigger executes and sets fake_response if needed
        assert pre_result.fake_response is None  # Because we need sync
        
        # Post-phase: Only post-trigger is executed
        post_result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234))
        
        # Post returns None (internal handling)
        assert post_result is None

    @pytest.mark.asyncio
    async def test_on_gcode_pre_sets_should_forward_based_on_triggers(self):
        """Test that should_forward is determined by trigger behaviors."""
        configs = [
            CustomTriggerConfig(
                id="pre-capture",
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
        
        # Pre-trigger is CAPTURE, so should_forward is False
        assert result.should_forward is False
        assert result.fake_response == "ok"

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_forward_behavior(self):
        """Test on_gcode_pre with FORWARD behavior trigger."""
        configs = [
            CustomTriggerConfig(
                id="pre-forward",
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
        
        # FORWARD trigger means should_forward is True
        assert result.should_forward is True
        assert result.fake_response is None

    @pytest.mark.asyncio
    async def test_on_gcode_pre_with_post_forward_trigger(self):
        """Test on_gcode_pre recognizes when post-phase has FORWARD trigger."""
        configs = [
            CustomTriggerConfig(
                id="pre-capture",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="post-forward",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.FORWARD,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        # Even though pre-trigger is CAPTURE, post-trigger is FORWARD
        # so should_forward must be True to allow device communication
        assert result.should_forward is True
        assert result.should_synchronize is True

    @pytest.mark.asyncio
    async def test_multiple_pre_triggers_all_capture(self):
        """Test multiple pre-triggers all with CAPTURE behavior."""
        configs = [
            CustomTriggerConfig(
                id="pre-capture-1",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="pre-capture-2",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        
        # Both triggers match and are CAPTURE
        assert result.should_forward is False
        assert result.fake_response == "ok"

    @pytest.mark.asyncio
    async def test_multiple_post_triggers_mixed_behavior(self):
        """Test multiple post-triggers with mixed behavior."""
        configs = [
            CustomTriggerConfig(
                id="post-capture",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=True,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="post-forward",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M[89]",
                    behavior=TriggerBehavior.FORWARD,
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ]
        manager = TriggerManager(configs)
        
        # Pre-phase with no pre-triggers
        pre_result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        
        # Both post-triggers should be recognized as requiring sync
        assert pre_result.should_synchronize is True
        # And should_forward should be True due to post-forward trigger
        assert pre_result.should_forward is True
        
        # Post-phase execution
        post_result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234))
        
        # Both post-triggers are executed
        assert post_result is None

    @pytest.mark.asyncio
    async def test_no_triggers_match(self):
        """Test on_gcode_pre when no triggers match."""
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
        
        result = await manager.on_gcode_pre("G28", ("127.0.0.1", 1234))
        
        assert result.should_forward is True
        assert result.should_synchronize is False
        assert result.fake_response is None

    @pytest.mark.asyncio
    async def test_on_gcode_post_with_empty_post_triggers(self):
        """Test on_gcode_post when there are no post-phase triggers."""
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
        
        # Pre-phase
        pre_result = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        assert pre_result is not None
        
        # Post-phase with no matching post-triggers
        post_result = await manager.on_gcode_post("M8", ("127.0.0.1", 1234))
        
        assert post_result is None

    @pytest.mark.asyncio
    async def test_capture_nowait_in_pre_phase(self):
        """Test CAPTURE_NOWAIT behavior in pre-phase."""
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
        
        # CAPTURE_NOWAIT returns success immediately
        assert result.should_forward is False
        assert result.fake_response == "ok"
        assert result.should_synchronize is False

    @pytest.mark.asyncio
    async def test_forward_and_capture_nowait_mixed(self):
        """Test FORWARD and CAPTURE_NOWAIT triggers together."""
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
        
        # FORWARD triggers override, so should_forward is True
        assert result.should_forward is True

    @pytest.mark.asyncio
    async def test_sync_trigger_prevents_capture_response(self):
        """Test that presence of sync triggers prevents early capture response."""
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
        
        # Even though pre-trigger is CAPTURE, we can't return early
        # because we need sync for post-trigger
        assert result.should_synchronize is True
        assert result.should_forward is True
        assert result.fake_response is None

    @pytest.mark.asyncio
    async def test_multiple_gcode_commands_in_sequence(self):
        """Test processing multiple commands in sequence."""
        configs = [
            CustomTriggerConfig(
                id="m8-trigger",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    behavior=TriggerBehavior.CAPTURE,
                    synchronize=False,
                ),
                command="exit 0",
            ),
            CustomTriggerConfig(
                id="m9-trigger",
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
        
        # Process M8 (pre-trigger only)
        result1 = await manager.on_gcode_pre("M8", ("127.0.0.1", 1234))
        assert result1.should_forward is False
        assert result1.should_synchronize is False
        
        # Process M9 (has post-trigger)
        result2 = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        assert result2.should_synchronize is True
        
        # Post-phase for M9
        post_result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234))
        assert post_result is None

    @pytest.mark.asyncio
    async def test_synchronization_required_flag_consistency(self):
        """Test that should_synchronize flag is set correctly."""
        # Test 1: No sync triggers
        manager1 = TriggerManager([
            CustomTriggerConfig(
                id="pre",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M8",
                    synchronize=False,
                ),
                command="exit 0",
            ),
        ])
        result1 = await manager1.on_gcode_pre("M8", ("127.0.0.1", 1234))
        assert result1.should_synchronize is False
        
        # Test 2: With sync triggers
        manager2 = TriggerManager([
            CustomTriggerConfig(
                id="post",
                trigger=GCodeTriggerConfig(
                    type="gcode",
                    match="M9",
                    synchronize=True,
                ),
                command="exit 0",
            ),
        ])
        result2 = await manager2.on_gcode_pre("M9", ("127.0.0.1", 1234))
        assert result2.should_synchronize is True