"""Tests for two-stage trigger handling with synchronization.

Tests verify that triggers are executed in the correct phase:
- Pre-phase (on_gcode_pre): Triggers without synchronize flag
- Post-phase (on_gcode_post): Triggers with synchronize flag, after G4 P0
"""

import asyncio
import pytest

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
        assert result["triggered"] is True
        assert result["should_synchronize"] is False
        assert len(result["matching_triggers"]) == 1

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
        assert result["triggered"] is True
        assert result["should_synchronize"] is True
        # Pre-results should be None since the trigger requires sync
        assert result["pre_results"] is None
        assert len(result["matching_triggers"]) == 1

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
        
        # First get the matching triggers from pre-phase
        pre_result = await manager.on_gcode_pre("M9", ("127.0.0.1", 1234))
        matching_triggers = pre_result["matching_triggers"]
        
        # Now execute post-phase
        result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234), matching_triggers)
        
        assert result is not None
        assert result["post_triggered"] is True
        assert result["post_results"] is not None
        assert len(result["post_results"].results) == 1

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
        
        assert pre_result["triggered"] is True
        assert pre_result["should_synchronize"] is True
        assert pre_result["pre_results"] is not None
        assert len(pre_result["pre_results"].results) == 1
        assert pre_result["pre_results"].results[0].trigger_id == "pre-trigger"
        
        # Post-phase: Only post-trigger is executed
        matching_triggers = pre_result["matching_triggers"]
        post_result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234), matching_triggers)
        
        assert post_result["post_triggered"] is True
        assert len(post_result["post_results"].results) == 1
        assert post_result["post_results"].results[0].trigger_id == "post-trigger"

    @pytest.mark.asyncio
    async def test_on_gcode_pre_sets_should_forward_based_on_pre_triggers(self):
        """Test that should_forward is determined by pre-phase triggers."""
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
        assert result["should_forward"] is False
        assert result["fake_response"] == "ok"

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
        assert result["should_forward"] is True
        assert result["fake_response"] is None

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
        assert result["should_forward"] is True
        assert result["should_synchronize"] is True

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
        assert result["should_forward"] is False
        assert len(result["pre_results"].results) == 2

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
        assert pre_result["should_synchronize"] is True
        # And should_forward should be True due to post-forward trigger
        assert pre_result["should_forward"] is True
        
        # Post-phase execution
        matching_triggers = pre_result["matching_triggers"]
        post_result = await manager.on_gcode_post("M9", ("127.0.0.1", 1234), matching_triggers)
        
        # Both post-triggers are executed
        assert len(post_result["post_results"].results) == 2

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
        
        assert result["triggered"] is False
        assert result["should_forward"] is True
        assert result["should_synchronize"] is False
        assert len(result["matching_triggers"]) == 0

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
        
        # Post-phase with matching_triggers that have no post-phase ones
        matching_triggers = pre_result["matching_triggers"]
        post_result = await manager.on_gcode_post("M8", ("127.0.0.1", 1234), matching_triggers)
        
        assert post_result["post_triggered"] is False
        assert post_result["post_results"] is None

    @pytest.mark.asyncio
    async def test_backward_compatibility_on_gcode(self):
        """Test that on_gcode still works for backward compatibility."""
        configs = [
            CustomTriggerConfig(
                id="trigger",
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
        
        # Call old-style on_gcode
        result = await manager.on_gcode("M8", ("127.0.0.1", 1234))
        
        # Should work and return pre-phase results
        assert result is not None
        assert result["triggered"] is True
        assert "matching_triggers" in result