"""
Trigger package - Contains trigger and event management.

This package provides:
- Trigger: Base trigger class for GCode event handling
- StateTrigger: Trigger class for device state change events
- TriggerManager: Manager for triggers and events
- TriggersConfig: Configuration for triggers
- CustomTriggerConfig: Configuration data class for custom triggers
"""

from .trigger import Trigger, StateTrigger
from .trigger_manager import TriggerManager
from .triggers_config import CustomTriggerConfig

__all__ = [
    "Trigger",
    "StateTrigger",
    "TriggerManager",
    "CustomTriggerConfig",
]
