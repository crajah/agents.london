"""Factory for the agent.london Civilization Engine.

One engine exists: Google ADK (user decision 2026-09-04, the native
python engine removed). The factory survives as the single construction
point -- and it FAILS LOUDLY. The old version fell back between engines
on any import error, which meant a broken dependency silently changed
which brain the platform ran on.
"""
import logging

from backend.civilization_interface import AbstractCivilizationEngine

logger = logging.getLogger(__name__)


def get_civilization_engine() -> AbstractCivilizationEngine:
    from backend.civilization_adk import GoogleADKCivilizationEngine
    logger.info("[Civilization Factory] Google ADK engine")
    return GoogleADKCivilizationEngine()
