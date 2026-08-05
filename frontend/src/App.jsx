import React, { useState, useEffect } from 'react';
import { ThemeProvider, CssBaseline, Box } from '@mui/material';
import theme from './theme';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import ChatbotView from './components/ChatbotView';
import PlaygroundView from './components/PlaygroundView';
import CivilizationGraphView from './components/CivilizationGraphView';
import AgentRegistryView from './components/AgentRegistryView';
import ToolRegistryView from './components/ToolRegistryView';
import SharedMemoryView from './components/SharedMemoryView';
import GuardrailsView from './components/GuardrailsView';
import SSOModal from './components/SSOModal';
import MaterializeAgentModal from './components/MaterializeAgentModal';
import AuthLockScreen from './components/AuthLockScreen';
import BYOMModal from './components/BYOMModal';
import ProjectTabsBar from './components/ProjectTabsBar';
import AgentDiscoveryView from './components/AgentDiscoveryView';
import DocumentRegistryView from './components/DocumentRegistryView';

export default function App() {
  const [userSession, setUserSession] = useState(null); // null = locked authentication wall

  const [currentTab, setCurrentTab] = useState('chatbot');
  const [ssoModalOpen, setSsoModalOpen] = useState(false);
  const [materializeModalOpen, setMaterializeModalOpen] = useState(false);
  const [byomModalOpen, setByomModalOpen] = useState(false);

  const [state, setState] = useState({
    orgId: 'org_london_meta',
    userId: 'user_chandan',
    projectId: 'proj_alpha_civilization',
    wsConnected: true,
    availableModels: [
      { id: 'MiniMax-M2.7', name: 'MiniMax M2.7', provider: 'MiniMax AI', context_window: 128000, status: 'active' },
      { id: 'gpt-oss-120b', name: 'GPT-OSS 120B', provider: 'OpenAI / OSS', context_window: 128000, status: 'active' },
      { id: 'Meta-Llama-3.3-70B-Instruct', name: 'Meta Llama 3.3 70B Instruct', provider: 'Meta AI', context_window: 128000, status: 'active' },
      { id: 'gemma-4-31B-it', name: 'Gemma 4 31B Instruct', provider: 'Google DeepMind', context_window: 131072, status: 'active' },
      { id: 'DeepSeek-V3.1', name: 'DeepSeek V3.1', provider: 'DeepSeek AI', context_window: 128000, status: 'active' },
      { id: 'DeepSeek-V3.2', name: 'DeepSeek V3.2', provider: 'DeepSeek AI', context_window: 128000, status: 'active' },
      { id: 'text-embedding-3-small', name: 'Text Embedding 3 Small', provider: 'OpenAI / Embeddings', context_window: 8191, status: 'active' }
    ],
    tools: [
      { tool_id: 'mcp-google-search', name: 'Google Search (GCP API)', scope_type: 'org', endpoint_url: 'http://tool-registry-service.default.svc.cluster.local:8002/tools/google-search', input_schema: { query: 'string', num_results: 'int' } },
      { tool_id: 'mcp-pgvector-search', name: 'pgvector Vector Search', scope_type: 'org', endpoint_url: 'http://localhost:8002/tools/pgvector', input_schema: { query_vector: 'list[float]' } },
      { tool_id: 'mcp-redis-queue', name: 'Redis Event Queue', scope_type: 'project', endpoint_url: 'http://localhost:8002/tools/redis', input_schema: { channel: 'str' } }
    ]
  });

  useEffect(() => {
    async function fetchModels() {
      try {
        const res = await fetch('/api/models');
        if (res.ok) {
          const data = await res.json();
          if (data.models) {
            setState(prev => ({ ...prev, availableModels: data.models, routerSource: data.source }));
          }
        }
      } catch (e) {
        console.log('Could not fetch models from backend:', e);
      }
    }
    fetchModels();
  }, []);

  const handleAuthenticate = (session) => {
    setUserSession(session);
    setState(prev => ({
      ...prev,
      orgId: session.orgId,
      userId: session.userId
    }));
  };

  const handleSSOLoginSuccess = (email) => {
    const clean = email.toLowerCase().trim();
    const parts = clean.split('@');
    const userPart = (parts[0] || 'user').replace(/[^a-z0-9]/g, '_');
    const domainPart = parts[1] || 'gmail.com';
    const sanitizedDomain = domainPart.replace(/[^a-z0-9]/g, '_');

    const isGeneric = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'icloud.com', 'protonmail.com'].includes(domainPart);
    const orgId = isGeneric ? `org_user_${userPart}_${sanitizedDomain}` : `org_${sanitizedDomain}`;
    const userId = `user_${userPart}`;

    handleAuthenticate({ email: clean, orgId, userId, isGeneric });
  };

  const handleLogout = () => {
    setUserSession(null);
  };

  const handleMaterializeSubmit = async (data) => {
    try {
      const res = await fetch('/api/agents/materialize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org_id: state.orgId,
          project_id: state.projectId,
          user_id: state.userId,
          agent_name: data.name,
          system_prompt: data.systemPrompt,
          parent_agent_id: data.parentId || null,
          tools: data.tools || [],
        })
      });
      if (!res.ok) console.error('Materialize failed:', await res.text());
    } catch (e) {
      console.error('Materialize error:', e);
    }
  };

  const handleAddTool = (newTool) => {
    setState(prev => ({
      ...prev,
      tools: [newTool, ...prev.tools]
    }));
  };

  const handleAddCustomModel = (customModel) => {
    setState(prev => ({
      ...prev,
      availableModels: [customModel, ...prev.availableModels]
    }));
  };

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      {!userSession ? (
        /* Mandatory Authentication Wall / Registration Screen */
        <AuthLockScreen onAuthenticate={handleAuthenticate} />
      ) : (
        /* Full Application Dashboard Once Authenticated */
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'background.default' }}>
          {/* Top Header */}
          <Header
            state={state}
            setState={setState}
            userSession={userSession}
            onLogout={handleLogout}
            onOpenSSO={() => setSsoModalOpen(true)}
            onOpenMaterialize={() => setMaterializeModalOpen(true)}
            onOpenBYOM={() => setByomModalOpen(true)}
            onToggleMobileSidebar={() => setMobileSidebarOpen(prev => !prev)}
          />

          {/* Project Universes Sub-Header Tabs Bar */}
          <ProjectTabsBar state={state} setState={setState} />

          {/* Main Content Area */}
          <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
            {/* Left Sidebar (Desktop Inline + Mobile Drawer) */}
            <Sidebar
              currentTab={currentTab}
              setCurrentTab={setCurrentTab}
              state={state}
              mobileOpen={mobileSidebarOpen}
              onCloseMobile={() => setMobileSidebarOpen(false)}
            />

            {/* Active View Panel */}
            <Box component="main" sx={{ flex: 1, overflow: 'auto', p: { xs: 1, sm: 2 } }}>
              {currentTab === 'chatbot' && <ChatbotView state={state} />}
              {currentTab === 'playground' && <PlaygroundView state={state} />}
              {currentTab === 'discovery' && <AgentDiscoveryView state={state} />}
              {currentTab === 'civilization' && <CivilizationGraphView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} />}
              {currentTab === 'agents' && <AgentRegistryView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} />}
              {currentTab === 'tools' && <ToolRegistryView state={state} onAddTool={handleAddTool} />}
              {currentTab === 'documents' && <DocumentRegistryView currentProject={{ id: state.projectId }} orgId={state.orgId} />}
              {currentTab === 'sessions' && <SharedMemoryView state={state} />}
              {currentTab === 'guardrails' && <GuardrailsView state={state} />}
            </Box>
          </Box>

          {/* Modals */}
          <SSOModal
            open={ssoModalOpen}
            onClose={() => setSsoModalOpen(false)}
            onLoginSuccess={handleSSOLoginSuccess}
          />

          <MaterializeAgentModal
            open={materializeModalOpen}
            onClose={() => setMaterializeModalOpen(false)}
            state={state}
            onSubmit={handleMaterializeSubmit}
          />

          <BYOMModal
            open={byomModalOpen}
            onClose={() => setByomModalOpen(false)}
            state={state}
            onAddCustomModel={handleAddCustomModel}
          />
        </Box>
      )}
    </ThemeProvider>
  );
}
