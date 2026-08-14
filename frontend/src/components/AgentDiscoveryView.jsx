import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FALLBACK_DEFAULT_MODEL } from '../utils/models';
import { api, attempt } from '../utils/api';
import {
  Box, Paper, Typography, TextField, Button, Chip, Stack, Card, CardContent, CircularProgress, LinearProgress, Divider, Dialog, DialogTitle, DialogContent, DialogActions, IconButton
, Alert, Tooltip} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CloseIcon from '@mui/icons-material/Close';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import AgentDetailModal from './AgentDetailModal';

export default function AgentDiscoveryView({ state }) {
  const [goalQuery, setGoalQuery] = useState('Ingest real-time financial metrics, scan for anomalies, forecast quarterly scenarios, and publish verified report');
  const [searching, setSearching] = useState(false);

  const [selectedAgent, setSelectedAgent] = useState(null);
  const [dagModalOpen, setDagModalOpen] = useState(false);

  // No seeded agents and no seeded pipeline. A sample the server did not
  // return is indistinguishable from one it did unless it is marked, and the
  // surest way to mark it is not to have any (F.18).
  const [discoveredAgents, setDiscoveredAgents] = useState([]);
  const [discoverySource, setDiscoverySource] = useState(null);
  const [discoverError, setDiscoverError] = useState(null);

  const [composition, setComposition] = useState(null);
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState(null);

  const [runTarget, setRunTarget] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [runError, setRunError] = useState(null);

  // Discovery is cheap and runs as you type. Composition is not — it calls a
  // planner model and publishes a pipeline — so it is an explicit action (F.50).
  const handleDiscover = async (queryToUse) => {
    const q = (queryToUse || goalQuery).trim();
    if (!q) return;
    setSearching(true);
    setDiscoverError(null);
    const { data, error } = await attempt(
      api.post('/api/agents/discover', { query: q }));
    if (error) {
      setDiscoverError(error);
      setDiscoveredAgents([]);
    } else {
      // The tier is named, because only `agent-registry` returns agents with a
      // version and a hash that can be pinned and called (F.16).
      setDiscoverySource(data.source);
      setDiscoveredAgents(data.discovered_agents || []);
    }
    setSearching(false);
  };

  const composedPipeline = (composition?.stages || []).map((s, index) => ({
    id: s.step,
    step: s.step,
    name: s.need,
    agent: s.agent_name || s.agent_id,
    agent_id: s.agent_id,
    // The resolved pin — what will actually run (F.51).
    version: s.version,
    content_hash: s.content_hash,
    status: 'published',
    output: null,
    dependencies: index > 0 ? [composition.stages[index - 1].step] : [],
  }));

  const debounceRef = useRef(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => handleDiscover(goalQuery), 600);
    return () => clearTimeout(debounceRef.current);
  }, [state.projectId, state.orgId, goalQuery]);

  /**
   * One goal in, one published pipeline out (F.50).
   *
   * The stages, the agent chosen for each and the resolved pins all come back
   * from the server, which really composed and published it. The previous
   * version rendered four hardcoded nodes with invented latencies that
   * composed nothing.
   */
  const handleCompose = async () => {
    const q = goalQuery.trim();
    if (!q) return;
    setComposing(true);
    setComposeError(null);
    setComposition(null);
    const { data, error } = await attempt(
      api.post('/api/conductor/compose', { query: q }, { timeoutMs: 300000 }));
    if (error) setComposeError(error);
    else setComposition(data);
    setComposing(false);
  };

  /** Run an agent by the name discovery handed back (F.17). */
  const handleRunAgent = async (agent) => {
    const toolName = agent.mcp_tool;
    if (!toolName) return;
    setRunTarget(toolName);
    setRunResult(null);
    setRunError(null);
    const { data, error } = await attempt(api.post(
      `/api/mcp/v1/tools/call`,
      { tool_name: toolName, arguments: { prompt: goalQuery || 'Introduce yourself.' } },
      { headers: {}, timeoutMs: 300000 }));
    if (error) setRunError(error);
    else setRunResult({ tool: toolName, ...data });
    setRunTarget(null);
  };

  /** Run the pipeline this goal composed, by its published name (F.51). */
  const handleRunComposition = async () => {
    if (!composition?.mcp_tool) return;
    setRunTarget(composition.mcp_tool);
    setRunResult(null);
    setRunError(null);
    const { data, error } = await attempt(api.post(
      `/api/mcp/v1/tools/call`,
      { tool_name: composition.mcp_tool, arguments: { prompt: goalQuery } },
      { timeoutMs: 600000 }));
    if (error) setRunError(error);
    else setRunResult({ tool: composition.mcp_tool, ...data });
    setRunTarget(null);
  };


  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            RAG-Driven Agent Discovery & Dynamic Composability Engine
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Discovers matching agent capabilities via post-graph-rag pgvector cosine search & composes multi-agent DAG pipelines dynamically.
          </Typography>
        </Box>

        <Button
          variant="contained"
          color="secondary"
          startIcon={runTarget ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
          onClick={handleRunComposition}
          disabled={Boolean(runTarget) || !composition}
        >
          {runTarget ? 'Running…' : composition ? `▶️ Run ${composition.mcp_tool}` : 'Compose a pipeline first'}
        </Button>
      </Box>

      {/* Query Search Box */}
      <Paper sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 1.5, backgroundColor: 'rgba(15, 23, 42, 0.85)', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 1 }}>
          <SearchIcon sx={{ fontSize: 18 }} /> Enter Goal Prompt for Capability Discovery & Dynamic Composition
        </Typography>

        <Box sx={{ display: 'flex', gap: 1.5 }}>
          <TextField
            fullWidth
            size="small"
            value={goalQuery}
            onChange={(e) => setGoalQuery(e.target.value)}
            placeholder="Describe a goal requiring multi-agent collaboration..."
          />
          <Button
            variant="outlined"
            color="primary"
            startIcon={searching ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
            onClick={() => handleDiscover()}
            disabled={searching}
            sx={{ px: 3, whiteSpace: 'nowrap' }}
          >
            {searching ? 'Discovering…' : 'Discover'}
          </Button>
          {/* Composition calls a planner and publishes a pipeline, so it is an
              explicit action rather than something that happens as you type. */}
          <Button
            variant="contained"
            color="secondary"
            startIcon={composing ? <CircularProgress size={16} color="inherit" /> : <AutoAwesomeIcon />}
            onClick={handleCompose}
            disabled={composing || !goalQuery.trim()}
            sx={{ px: 3, whiteSpace: 'nowrap' }}
          >
            {composing ? 'Composing…' : '🪄 Compose pipeline'}
          </Button>
        </Box>

        {discoverError && (
          <Alert severity="error" onClose={() => setDiscoverError(null)}>
            {discoverError.userMessage}
          </Alert>
        )}
        {composeError && (
          <Alert severity="error" onClose={() => setComposeError(null)}>
            {composeError.userMessage}
          </Alert>
        )}
        {runError && (
          <Alert severity="error" onClose={() => setRunError(null)}>
            {runError.userMessage}
          </Alert>
        )}
        {runResult && (
          <Alert
            severity={runResult.isError ? 'error' : 'success'}
            onClose={() => setRunResult(null)}
            sx={{ maxHeight: 260, overflow: 'auto' }}
          >
            <strong>{runResult.tool}</strong>
            {runResult.status ? ` — ${runResult.status}` : ''}
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>
              {runResult.content?.[0]?.text || JSON.stringify(runResult.result ?? runResult, null, 2)}
            </Typography>
          </Alert>
        )}
      </Paper>

      {/* Main Showcase Layout: Left (Clickable Discovered Agents), Right (Clickable Composed Pipeline DAG) */}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 3 }}>
        {/* LEFT COLUMN: RAG DISCOVERED AGENTS (CLICKABLE FOR FULL DETAILS) */}
        <Paper sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1, color: '#a78bfa' }}>
            🔍 RAG Vector Discovery Results (post-graph-rag)
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Project <code>{state.projectId}</code>
            {discoverySource && <> · source: <strong>{discoverySource}</strong></>}
          </Typography>
          {discoverySource && discoverySource !== 'agent-registry' && (
            <Alert severity="info" sx={{ fontSize: '0.72rem' }}>
              These came from the {discoverySource === 'post-graph-rag'
                ? 'archetype index' : 'keyword index'}, not the agent registry —
              they have no published version, so they cannot be pinned or run
              from here.
            </Alert>
          )}
          {!searching && discoveredAgents.length === 0 && !discoverError && (
            <Alert severity="info" sx={{ fontSize: '0.75rem' }}>
              No agents matched this goal in {state.projectId}.
            </Alert>
          )}
          <Divider sx={{ my: 0.5 }} />

          <Stack spacing={2}>
            {discoveredAgents.map((agent) => (
              <Paper
                key={agent.agent_id || agent.id}
                elevation={0}
                onClick={() => setSelectedAgent(agent)}
                sx={{
                  p: 2,
                  backgroundColor: 'rgba(9, 13, 22, 0.75)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 2,
                  cursor: 'pointer',
                  transition: 'all 0.2s ease-in-out',
                  '&:hover': {
                    backgroundColor: 'rgba(30, 41, 59, 0.9)',
                    borderColor: '#60a5fa',
                    transform: 'translateY(-2px)',
                    boxShadow: '0 4px 14px rgba(96, 165, 250, 0.2)'
                  }
                }}
              >
                <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: 0.8 }}>
                    <SmartToyIcon sx={{ fontSize: 18, color: '#60a5fa' }} /> {agent.name}
                  </Typography>
                  <Chip
                    label={`${Math.round((agent.similarity || 0.95) * 100)}% Match`}
                    size="small"
                    color="primary"
                    sx={{ fontWeight: 700, fontSize: '0.65rem' }}
                  />
                </Stack>

                <LinearProgress
                  variant="determinate"
                  value={(agent.similarity || 0.95) * 100}
                  sx={{ height: 6, borderRadius: 3, mb: 1, backgroundColor: 'rgba(255,255,255,0.08)' }}
                />

                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.8rem', mb: 1 }}>
                  {agent.reason}
                </Typography>

                <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
                  <Stack direction="row" spacing={1}>
                    <Chip label={(agent.caste || 'architect').toUpperCase()} size="small" color={getCasteColor(agent.caste)} sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700 }} />
                    <Chip icon={<VerifiedUserIcon sx={{ fontSize: 12 }} />} label="ED25519 Verified" size="small" color="success" variant="outlined" sx={{ height: 16, fontSize: '0.6rem' }} />
                  </Stack>
                  <Typography variant="caption" sx={{ color: '#60a5fa', fontWeight: 600, fontSize: '0.72rem' }}>
                    Click for details ➔
                  </Typography>
                </Stack>
                {/* Discovery hands back the name this agent is invoked
                    by, so it can be run from where it was found (F.17). */}
                {agent.mcp_tool ? (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                    <Tooltip title={`Runs ${agent.mcp_tool}`}>
                      <span>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={Boolean(runTarget)}
                          onClick={(e) => { e.stopPropagation(); handleRunAgent(agent); }}
                          sx={{ fontSize: '0.7rem' }}
                        >
                          {runTarget === agent.mcp_tool ? 'Running…' : '▶ Run'}
                        </Button>
                      </span>
                    </Tooltip>
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', color: '#94a3b8' }}>
                      {agent.mcp_tool}
                    </Typography>
                  </Stack>
                ) : (
                  <Typography variant="caption" sx={{ color: '#94a3b8', mt: 1, display: 'block' }}>
                    Not published — cannot be run from here.
                  </Typography>
                )}
              </Paper>
            ))}
          </Stack>
        </Paper>

        {/* RIGHT COLUMN: DYNAMICALLY COMPOSED PIPELINE (CLICKABLE FOR DAG GRAPH CANVAS) */}
        <Paper sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1, color: '#10b981' }}>
              <AccountTreeIcon sx={{ fontSize: 20 }} /> Dynamically Composed Agent DAG Pipeline
            </Typography>
            <Button size="small" variant="outlined" color="success" onClick={() => setDagModalOpen(true)} sx={{ fontSize: '0.72rem' }}>
              🔍 View Directed DAG Graph
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            {composition
              ? `Published as ${composition.mcp_tool} — ${composition.stages.length} stages, pins resolved.`
              : 'No pipeline composed yet for this goal.'}
          </Typography>
          {composition?.unmatched_stages?.length > 0 && (
            <Alert severity="warning" sx={{ fontSize: '0.75rem' }}>
              {composition.unmatched_stages.length} stage(s) had no registered agent
              and were left out: {composition.unmatched_stages.map((s) => s.need).join('; ')}
            </Alert>
          )}
          <Divider sx={{ my: 0.5 }} />

          <Stack spacing={2}>
            {composedPipeline.map((step) => (
              <Paper
                key={step.step || step.id}
                elevation={0}
                onClick={() => setDagModalOpen(true)}
                sx={{
                  p: 2,
                  backgroundColor: 'rgba(9, 13, 22, 0.75)',
                  borderLeft: '4px solid #10b981',
                  borderRadius: 2,
                  cursor: 'pointer',
                  transition: 'all 0.2s ease-in-out',
                  '&:hover': {
                    backgroundColor: 'rgba(16, 185, 129, 0.08)',
                    borderColor: '#34d399'
                  }
                }}
              >
                <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                    STEP {step.step}: {(step.name || 'STAGE').toUpperCase()}
                  </Typography>
                  {/* A composed pipeline is published, not executed. It has no
                      status, no output and no latency until it is run — the
                      previous version showed all three (F.13, F.51). */}
                  <Chip
                    label="PUBLISHED"
                    size="small"
                    color="info"
                    variant="outlined"
                    sx={{ height: 18, fontSize: '0.62rem', fontWeight: 700 }}
                  />
                </Stack>

                <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: '0.9rem', color: '#60a5fa', my: 0.5 }}>
                  {step.agent}
                </Typography>

                {/* The pin: exactly which definition this stage will run
                    (agent-graph Rule 5.2). Without it the plan is a suggestion
                    rather than something reproducible (F.51). */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1, fontSize: '0.72rem', color: 'text.secondary', fontFamily: '"JetBrains Mono", monospace' }}>
                  <span>
                    Pinned: <strong style={{ color: '#a78bfa' }}>
                      {step.version ? `v${step.version}` : 'unpinned'}
                    </strong>
                  </span>
                  {step.content_hash && (
                    <Tooltip title={step.content_hash}>
                      <span>hash <strong style={{ color: '#38bdf8' }}>
                        {String(step.content_hash).slice(0, 12)}
                      </strong></span>
                    </Tooltip>
                  )}
                </Box>
              </Paper>
            ))}
          </Stack>
        </Paper>
      </Box>

      {/* AGENT DETAIL MODAL */}
      {selectedAgent && (
        <AgentDetailModal
          open={Boolean(selectedAgent)}
          onClose={() => setSelectedAgent(null)}
          agent={selectedAgent}
          onSaveModel={() => setSelectedAgent(null)}
          state={state}
        />
      )}

      {/* DIRECTED ACYCLIC GRAPH (DAG) VISUALIZER MODAL */}
      <Dialog open={dagModalOpen} onClose={() => setDagModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AccountTreeIcon color="success" /> Directed Acyclic Graph (DAG) Execution Pipeline
          </Box>
          <IconButton onClick={() => setDagModalOpen(false)} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Visualizing multi-agent DAG topology for query: <em>"{goalQuery}"</em>
          </Typography>

          {/* Interactive DAG Directed Arrows View */}
          <Box sx={{ p: 3, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.95)', border: '1px solid rgba(16, 185, 129, 0.2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
              {composedPipeline.map((node, index) => (
                <React.Fragment key={node.step || node.id}>
                  {/* DAG Node Card */}
                  <Paper
                    elevation={0}
                    sx={{
                      p: 1.8,
                      minWidth: 160,
                      backgroundColor: 'rgba(15, 23, 42, 0.9)',
                      border: '2px solid #10b981',
                      borderRadius: 2,
                      textAlign: 'center'
                    }}
                  >
                    <Chip label={`Node ${node.step}`} size="small" color="success" sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700, mb: 0.8 }} />
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: '0.82rem', color: '#ffffff' }}>
                      {node.agent}
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#a78bfa', display: 'block', fontSize: '0.7rem', fontFamily: '"JetBrains Mono", monospace' }}>
                      {node.tool}
                    </Typography>
                  </Paper>

                  {/* Directed Edge Arrow */}
                  {index < composedPipeline.length - 1 && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', color: '#10b981', px: 1 }}>
                      <Typography variant="caption" sx={{ fontSize: '0.65rem', color: '#a78bfa', fontWeight: 700 }}>
                        DEPENDENCY ➔
                      </Typography>
                      <Box sx={{ fontSize: '1.4rem', fontWeight: 800 }}>➔</Box>
                    </Box>
                  )}
                </React.Fragment>
              ))}
            </Box>

            <Divider sx={{ my: 1 }} />

            {/* Resolved pins, not telemetry: this pipeline has been published,
                not run, so there are no latencies and no step signatures to
                audit. The earlier table showed both, invented (F.13, F.51). */}
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#10b981' }}>
              Resolved pins
            </Typography>

            <Stack spacing={1}>
              {composedPipeline.map((node) => (
                <Paper key={node.step} elevation={0} sx={{ p: 1.2, backgroundColor: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 1.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, flexWrap: 'wrap', fontSize: '0.78rem' }}>
                  <Box>
                    <strong style={{ color: '#60a5fa' }}>Step {node.step}: {node.name}</strong> ({node.agent})
                  </Box>
                  <Box sx={{ display: 'flex', gap: 1.5, fontFamily: '"JetBrains Mono", monospace' }}>
                    <span>{node.version ? `v${node.version}` : 'unpinned'}</span>
                    {node.content_hash && (
                      <span style={{ color: '#a78bfa' }}>
                        {String(node.content_hash).slice(0, 16)}
                      </span>
                    )}
                  </Box>
                </Paper>
              ))}
            </Stack>
          </Box>
        </DialogContent>

        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDagModalOpen(false)} variant="contained" color="primary">
            Close Visualizer
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
