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
        session_id: Optional[str] = None,
        isolation_mode: str = "isolated"
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
        """Provisions full Prime Node agents hierarchy for project."""
        pass

    @abstractmethod
    async def create_user(self, org_id: str, username: str, email: str) -> Dict[str, Any]:
        """Creates user entity in civilization system."""
        pass

    @abstractmethod
    async def create_project(
        self,
        org_id: str,
        user_id: str,
        project_name: str,
        constitution_rules: Optional[list] = None
    ) -> Dict[str, Any]:
        """Creates project universe and auto-registers Prime Caste scaffolding."""
        pass

    @abstractmethod
    async def materialize_worker_agent(
        self,
        org_id: str,
        project_id: str,
        user_id: str,
        agent_name: str,
        telos: str = "Execute specialized sub-task objectives",
        system_prompt: str = "Default worker agent prompt",
        parent_agent_id: Optional[str] = None,
        tools: Optional[list] = None,
        custom_guardrails: Optional[list] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Materializes an agent and registers it with the Agent Registry microservice & post-graph."""
        pass

    @abstractmethod
    async def get_all_project_agents(self, org_id: str, project_id: str) -> list:
        """Retrieves all registered agents for a project from the Agent Registry microservice & post-graph."""
        pass

    @abstractmethod
    async def index_agent_registry_for_rag(self, org_id: str, project_id: str) -> Dict[str, Any]:
        """Indexes agent registry specifications into post-graph-rag."""
        pass

    @abstractmethod
    async def search_agent_registry_rag(self, org_id: str, project_id: str, query_prompt: str, top_k: int = 3) -> list:
        """Searches post-graph-rag for matching candidate agents/workflows in the agent registry."""
        pass

    @abstractmethod
    async def register_pipeline_in_registry(
        self,
        org_id: str,
        project_id: str,
        pipeline_name: str,
        task_prompt: str,
        graph_nodes: list,
        graph_edges: list,
        assigned_agent_ids: list
    ) -> Dict[str, Any]:
        """Registers a multi-agent execution pipeline graph in Agent Registry microservice, post-graph, and post-graph-rag."""
        pass

    @abstractmethod
    async def get_all_registered_tools(self, org_id: str, project_id: str) -> list:
        """Retrieves all registered MCP tools from the Tool Registry microservice & post-graph."""
        pass

    @abstractmethod
    async def index_tool_registry_for_rag(self, org_id: str, project_id: str) -> Dict[str, Any]:
        """Indexes tool registry specifications into post-graph-rag under tool_registry_rag."""
        pass

    @abstractmethod
    async def search_tool_registry_rag(self, org_id: str, project_id: str, query_prompt: str, top_k: int = 3) -> list:
        """Searches post-graph-rag for matching candidate MCP tools in the tool registry."""
        pass


