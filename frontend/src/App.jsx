import React, { useState } from 'react';
import { ThemeProvider, CssBaseline, Box } from '@mui/material';
import theme from './theme';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import PlaygroundView from './components/PlaygroundView';
import CivilizationGraphView from './components/CivilizationGraphView';
import AgentRegistryView from './components/AgentRegistryView';
import ToolRegistryView from './components/ToolRegistryView';
import SharedMemoryView from './components/SharedMemoryView';
import GuardrailsView from './components/GuardrailsView';
import SSOModal from './components/SSOModal';
import MaterializeAgentModal from './components/MaterializeAgentModal';

export default function App() {
  const [currentTab, setCurrentTab] = useState('playground');
  const [ssoModalOpen, setSsoModalOpen] = useState(false);
  const [materializeModalOpen, setMaterializeModalOpen] = useState(false);

  const [state, setState] = useState({
    orgId: 'org_london_meta',
    userId: 'user_chandan',
    projectId: 'proj_alpha_civilization',
    wsConnected: true,
    tools: [
      { tool_id: 'mcp-pgvector-search', name: 'pgvector Vector Search', scope_type: 'org', endpoint_url: 'http://localhost:8002/tools/pgvector', input_schema: { query_vector: 'list[float]' } },
      { tool_id: 'mcp-redis-queue', name: 'Redis Event Queue', scope_type: 'project', endpoint_url: 'http://localhost:8002/tools/redis', input_schema: { channel: 'str' } }
    ]
  });

  const handleSSOLoginSuccess = (email) => {
    const clean = email.toLowerCase().trim();
    const parts = clean.split('@');
    const userPart = (parts[0] || 'user').replace(/[^a-z0-9]/g, '_');
    const domainPart = parts[1] || 'gmail.com';
    const sanitizedDomain = domainPart.replace(/[^a-z0-9]/g, '_');

    const isGeneric = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'icloud.com', 'protonmail.com'].includes(domainPart);
    const orgId = isGeneric ? `org_user_${userPart}_${sanitizedDomain}` : `org_${sanitizedDomain}`;
    const userId = `user_${userPart}`;

    setState(prev => ({
      ...prev,
      orgId,
      userId
    }));
  };

  const handleMaterializeSubmit = (data) => {
    console.log('Materializing agent:', data);
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'background.default' }}>
        {/* Top Header */}
        <Header
          state={state}
          setState={setState}
          onOpenSSO={() => setSsoModalOpen(true)}
          onOpenMaterialize={() => setMaterializeModalOpen(true)}
        />

        {/* Main Content Area */}
        <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* Left Sidebar */}
          <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} />

          {/* Active View Panel */}
          <Box component="main" sx={{ flex: 1, overflow: 'hidden' }}>
            {currentTab === 'playground' && <PlaygroundView state={state} />}
            {currentTab === 'civilization' && <CivilizationGraphView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} />}
            {currentTab === 'agents' && <AgentRegistryView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} />}
            {currentTab === 'tools' && <ToolRegistryView state={state} />}
            {currentTab === 'sessions' && <SharedMemoryView />}
            {currentTab === 'guardrails' && <GuardrailsView />}
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
      </Box>
    </ThemeProvider>
  );
}
