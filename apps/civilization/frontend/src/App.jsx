import React, { useState, useEffect, useMemo } from 'react';
import { ThemeProvider, CssBaseline, Box, useMediaQuery } from '@mui/material';
import { darkTheme, lightTheme } from './theme';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import ChatbotView from './components/ChatbotView';
import PlaygroundView from './components/PlaygroundView';
import CivilizationGraphView from './components/CivilizationGraphView';
import AgentRegistryView from './components/AgentRegistryView';
import ToolRegistryView from './components/ToolRegistryView';
import SharedMemoryView from './components/SharedMemoryView';
import GuardrailsView from './components/GuardrailsView';
import MaterializeAgentModal from './components/MaterializeAgentModal';
import AuthLockScreen, { authorityLoginUrl } from './components/AuthLockScreen';
import BYOMModal from './components/BYOMModal';
import ProjectTabsBar from './components/ProjectTabsBar';
import AgentDiscoveryView from './components/AgentDiscoveryView';
import DocumentRegistryView from './components/DocumentRegistryView';
import { api, attempt, setApiContext } from './utils/api';
import { readRoute, writeRoute } from './utils/route';
import { fetchModels, resetModelCache } from './utils/models';
import { toSession } from './utils/tenancy';

/** Events that change the population, and so invalidate what the lists show. */
const RELOAD_EVENTS = new Set([
  'agent_materialized', 'project_created', 'agent_registered',
  'pipeline_materialized_and_registered', 'workflow_completed',
]);

export default function App() {
  // Theme: 'system' | 'light' | 'dark'
  const [themePreference, setThemePreference] = useState(() => localStorage.getItem('theme') || 'system');
  const systemPrefersDark = useMediaQuery('(prefers-color-scheme: dark)');
  const isDark = themePreference === 'dark' || (themePreference === 'system' && systemPrefersDark);
  const activeTheme = useMemo(() => isDark ? darkTheme : lightTheme, [isDark]);

  const handleThemeChange = (mode) => {
    setThemePreference(mode);
    localStorage.setItem('theme', mode);
  };

  const [userSession, setUserSession] = useState(null); // null = locked authentication wall

  // F.4 — the view and the project are addressable. Without this a person
  // cannot send a colleague a link to what they are looking at, and a refresh
  // always lands back on the chatbot.
  const [currentTab, setCurrentTab] = useState(() => readRoute().view);
  const [materializeModalOpen, setMaterializeModalOpen] = useState(false);
  const [byomModalOpen, setByomModalOpen] = useState(false);

  const [state, setState] = useState({
    orgId: 'org_london_meta',
    userId: 'user_chandan',
    projectId: 'proj_alpha_civilization',
    wsConnected: false,
    // No seeded model list either. It named two models the router had stopped
    // serving, so a user could select one before the fetch replaced it (F.41).
    availableModels: [],
    // No `tools` here. The shell used to hold a copy of the tool catalogue and
    // prepend to it on registration, so the interface showed tools the server
    // did not have; the tools view now reads the registry (F.53).
  });

  useEffect(() => {
    setApiContext({ orgId: state.orgId, projectId: state.projectId });
  }, [state.orgId, state.projectId]);

  // The URL follows the interface…
  useEffect(() => {
    writeRoute({ view: currentTab, project: state.projectId });
  }, [currentTab, state.projectId]);

  // …and the interface follows the back button.
  useEffect(() => {
    const onPop = () => {
      const route = readRoute();
      setCurrentTab(route.view);
      if (route.project) {
        setState((prev) => (prev.projectId === route.project
          ? prev
          : { ...prev, projectId: route.project }));
      }
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  // One module owns the catalogue, cached for the session (F.41).
  useEffect(() => {
    let cancelled = false;
    fetchModels().then((catalogue) => {
      if (cancelled) return;
      setState((prev) => ({
        ...prev,
        availableModels: catalogue.models,
        routerSource: catalogue.source,
        modelWarning: catalogue.warning,
      }));
    });
    return () => { cancelled = true; };
  }, []);

  // WebSocket connection for real-time civilization events
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/civilization`;
    let ws;
    let reconnectTimer;
    let retryCount = 0;
    const MAX_RETRIES = 5;

    function connect() {
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        return; // WebSocket constructor failed (e.g., invalid URL)
      }
      ws.onopen = () => {
        retryCount = 0;
        setState(prev => ({ ...prev, wsConnected: true }));
      };
      ws.onclose = () => {
        setState(prev => ({ ...prev, wsConnected: false }));
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          const delay = Math.min(5000 * Math.pow(2, retryCount - 1), 60000);
          reconnectTimer = setTimeout(connect, delay);
        }
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          // F.48 — events update the screen. They used to be logged to the
          // console, which is a connection that costs something and returns
          // nothing.
          setState((prev) => ({
            ...prev,
            lastEvent: { type: msg.type, at: Date.now(), data: msg.data },
            // Anything that changes the population invalidates the lists that
            // show it; the views refetch on this token rather than being
            // patched from an event payload the server did not confirm.
            populationVersion: RELOAD_EVENTS.has(msg.type)
              ? (prev.populationVersion || 0) + 1
              : (prev.populationVersion || 0),
          }));
        } catch { /* ignore non-JSON */ }
      };
    }
    connect();

    return () => {
      retryCount = MAX_RETRIES; // prevent reconnect on unmount
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, []);

  const handleAuthenticate = (session) => {
    setUserSession(session);
    setState(prev => ({
      ...prev,
      orgId: session.orgId,
      userId: session.userId,
      verified: Boolean(session.verified),
    }));
  };

  // The only doors in are the authority's Google and Microsoft flows. The
  // authority redirects back with a short-lived RS256 token (URL param and
  // cookie); the backend verifies it against the authority's JWKS and answers
  // with the tenancy — one rule, one place (F.5), verified only (F.7).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('authority_token');
    if (fromUrl) {
      params.delete('authority_token');
      const qs = params.toString();
      window.history.replaceState({}, '',
        window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash);
    }
    const fromCookie = document.cookie.split('; ')
      .find((c) => c.startsWith('authority_token='))?.split('=').slice(1).join('=');
    const token = fromUrl || fromCookie;
    if (!token) return;
    attempt(api.post('/api/auth/authority/session', { token }, { scoped: false }))
      .then(({ data, error }) => {
        if (error) console.error('Authority session rejected:', error.userMessage);
        else handleAuthenticate(toSession(data));
      });
  }, []);

  const handleLogout = () => {
    document.cookie = 'authority_token=; Max-Age=0; path=/';
    setUserSession(null);
  };

  const handleMaterializeSubmit = async (data) => {
    const { error } = await attempt(api.post('/api/agents/materialize', {
      user_id: state.userId,
      agent_name: data.name,
      system_prompt: data.systemPrompt,
      parent_agent_id: data.parentId || null,
      tools: data.tools || [],
    }));
    if (error) console.error('Materialize failed:', error.userMessage);
  };

  // Registering a tool refetches; it does not prepend to an array the server
  // does not know about (F.53).
  const [toolsVersion, setToolsVersion] = useState(0);
  const handleAddTool = () => setToolsVersion((n) => n + 1);

  // A custom model is saved server-side; the catalogue is re-read rather than
  // patched locally (F.53).
  const handleAddCustomModel = () => {
    resetModelCache();
    fetchModels().then((catalogue) => {
      setState((prev) => ({ ...prev, availableModels: catalogue.models }));
    });
  };

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <ThemeProvider theme={activeTheme}>
      <CssBaseline />

      {!userSession ? (
        /* Mandatory Authentication Wall / Registration Screen */
        <AuthLockScreen />
      ) : (
        /* Full Application Dashboard Once Authenticated */
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'background.default' }}>
          {/* Top Header */}
          <Header
            state={state}
            setState={setState}
            userSession={userSession}
            onLogout={handleLogout}
            onOpenSSO={() => { window.location.href = authorityLoginUrl('google'); }}
            onOpenMaterialize={() => setMaterializeModalOpen(true)}
            onOpenBYOM={() => setByomModalOpen(true)}
            onToggleMobileSidebar={() => setMobileSidebarOpen(prev => !prev)}
            themePreference={themePreference}
            onThemeChange={handleThemeChange}
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
              {currentTab === 'civilization' && <CivilizationGraphView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} reloadToken={state.populationVersion || 0} />}
              {currentTab === 'agents' && <AgentRegistryView state={state} onOpenMaterialize={() => setMaterializeModalOpen(true)} reloadToken={state.populationVersion || 0} />}
              {currentTab === 'tools' && <ToolRegistryView state={state} onAddTool={handleAddTool} reloadToken={toolsVersion} />}
              {currentTab === 'documents' && <DocumentRegistryView currentProject={{ id: state.projectId }} orgId={state.orgId} />}
              {currentTab === 'sessions' && <SharedMemoryView state={state} />}
              {currentTab === 'guardrails' && <GuardrailsView state={state} />}
            </Box>
          </Box>

          {/* Modals */}
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
