"""Factory Router for agent.london Civilization Engine.

Dynamically selects between Native Python Engine and Google ADK (Agent Development Kit) Engine
based on CIVILIZATION_ENGINE_TYPE environment variable.
"""
import os
import logging
from backend.civilization_interface import AbstractCivilizationEngine

logger = logging.getLogger(__name__)

def get_civilization_engine() -> AbstractCivilizationEngine:
    engine_type = os.getenv("CIVILIZATION_ENGINE_TYPE", "GOOGLE_ADK").strip().upper()
    logger.info(f"[Civilization Factory] Selected engine strategy: '{engine_type}'")

    if engine_type == "NATIVE":
        try:
            from backend.civilization import AgentCivilizationEngine
            return AgentCivilizationEngine()
        except Exception as e:
            logger.error(f"Failed to instantiate AgentCivilizationEngine: {e}, falling back to Google ADK engine.")

    # Default Google ADK Engine
    try:
        from backend.civilization_adk import GoogleADKCivilizationEngine
        return GoogleADKCivilizationEngine()
    except Exception as e:
        logger.error(f"Failed to instantiate GoogleADKCivilizationEngine: {e}, falling back to Native engine.")
        from backend.civilization import AgentCivilizationEngine
        return AgentCivilizationEngine()
