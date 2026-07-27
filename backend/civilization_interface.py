"""Abstract Base Interface for agent.london Civilization Engine.

Defines the unified engine contract for both Native Python and Google ADK implementations.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class AbstractCivilizationEngine(ABC):

    @abstractmethod
    async def process_user_prompt_with_llm(
        self,
        org_id: str,
        project_id: str,
        user_prompt: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates user prompt with LLM intent router and executes selected mode."""
        pass

    @abstractmethod
    async def run_conductor_orchestration(
        self,
        org_id: str,
        project_id: str,
        task_prompt: str,
        depth: int = 0,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """Runs multi-agent Conductor orchestration across Prime Agent nodes."""
        pass

    @abstractmethod
    async def run_react_loop(
        self,
        org_id: str,
        project_id: str,
        user_prompt: str,
        max_iterations: int = 4
    ) -> Dict[str, Any]:
        """Runs iterative ReAct reasoning loop with tool calls."""
        pass

    @abstractmethod
    async def provision_civilization_for_project(
        self,
        org_id: str,
        user_id: str,
        project_id: str
    ) -> Dict[str, Any]:
        """Provisions full 28 Prime Node agents hierarchy for project."""
        pass
