import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, attempt, stream } from '../utils/api';
import { chatModels, fetchModels, FALLBACK_DEFAULT_MODEL } from '../utils/models';
import {
  Box, Paper, Typography, TextField, Button, Chip, Stack, Alert, Divider,
  CircularProgress, LinearProgress, Tooltip, IconButton, Accordion,
  AccordionSummary, AccordionDetails, FormControl, InputLabel, Select, MenuItem,
  ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import AutoFormatDetectorRenderer from './AutoFormatDetectorRenderer';
import RunDetailModal from './RunDetailModal';

/**
 * From a prompt to an answer, with the work visible in between.
 *
 * The old playground was a chat window: you typed, a spinner spun, and a
 * message appeared. Everything interesting — that a founder decided how to
 * route the request, that a planner broke it into stages, that each stage was
 * matched to a published agent by vector search, that the composition was
 * validated and pinned before anything ran, that each agent produced a real
 * intermediate result the next one consumed — happened invisibly. What it did
 * show was invented: two fixed process steps at "64ms" and "28ms", a random
 * ed25519 signature and a token count of 320, appended after every turn
 * including the failed ones.
 *
 * This shows the actual journey, live, from a server-sent-event stream where
 * every event is emitted at the moment the thing it describes happens:
 *
 *   intake → plan → match → publish → run each agent → answer
 *
 * "Thinking" here means what an agent genuinely produced and how long it
 * genuinely took. There is no typing animation and no synthesised reasoning
 * narration: an interface that mimics thought is making a claim about a
 * process it cannot see.
 */

const PHASES = [
  { key: 'intake', label: 'Intake', hint: 'A founder decides what to do with the request' },
  { key: 'plan', label: 'Plan', hint: 'The goal is broken into stages' },
  { key: 'match', label: 'Match', hint: 'Each stage is matched to a published agent' },
  { key: 'publish', label: 'Publish', hint: 'The pipeline is validated and pinned' },
  { key: 'run', label: 'Run', hint: 'Each agent runs on the previous one’s output' },
  { key: 'answer', label: 'Answer', hint: 'The last stage’s output is the deliverable' },
];

function elapsed(sinceMs) {
  const secs = (Date.now() - sinceMs) / 1000;
  return secs < 60 ? `${secs.toFixed(1)}s` : `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
}

/** A live seconds counter, so a slow agent looks busy rather than broken. */
function Elapsed({ since }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 200);
    return () => clearInterval(timer);
  }, []);
  return <span>{elapsed(since)}</span>;
}

function StageCard({ stage }) {
  const running = stage.status === 'running';
  const failed = stage.status === 'failed';
  const done = stage.status === 'done';

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2, borderRadius: 2,
        backgroundColor: 'rgba(9, 13, 22, 0.85)',
        borderLeft: `4px solid ${failed ? '#ef4444' : done ? '#10b981' : running ? '#f59e0b' : '#334155'}`,
        transition: 'border-color 0.2s ease',
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
        <Stack direction="row" spacing={1} alignItems="center">
          {failed ? <ErrorOutlineIcon sx={{ fontSize: 18, color: '#ef4444' }} />
            : done ? <CheckCircleIcon sx={{ fontSize: 18, color: '#10b981' }} />
              : running ? <CircularProgress size={14} />
                : <RadioButtonUncheckedIcon sx={{ fontSize: 18, color: '#475569' }} />}
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#e2e8f0' }}>
            {stage.index != null ? `${stage.index + 1}. ` : ''}{stage.step}
          </Typography>
          {stage.agent_name && (
            <Chip label={stage.agent_name} size="small" color="primary"
                  sx={{ height: 18, fontSize: '0.62rem', fontWeight: 700 }} />
          )}
        </Stack>

        <Stack direction="row" spacing={1} alignItems="center">
          {/* The pin: exactly which definition ran (F.51). */}
          {stage.version && (
            <Tooltip title={stage.content_hash || 'no content hash recorded'}>
              <Typography variant="caption"
                          sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#a78bfa' }}>
                v{stage.version}
                {stage.content_hash && ` · ${String(stage.content_hash).slice(7, 17)}`}
              </Typography>
            </Tooltip>
          )}
          {running && (
            <Typography variant="caption" sx={{ color: '#f59e0b', fontWeight: 700 }}>
              <Elapsed since={stage.startedAt} />
            </Typography>
          )}
          {/* Measured, or absent. Never invented (F.14). */}
          {stage.duration_ms != null && (
            <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 700 }}>
              {stage.duration_ms}ms
            </Typography>
          )}
        </Stack>
      </Stack>

      {stage.need && (
        <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mt: 0.5 }}>
          {stage.need}
        </Typography>
      )}

      {stage.match_distance != null && (
        <Typography variant="caption" sx={{ color: '#64748b', display: 'block' }}>
          matched by vector distance {Number(stage.match_distance).toFixed(4)}
        </Typography>
      )}

      {/* What this agent was actually handed — the previous stage's output. */}
      {stage.input && (
        <Accordion elevation={0} sx={{
          mt: 1, backgroundColor: 'rgba(15, 23, 42, 0.6)',
          border: '1px solid rgba(255,255,255,0.06)', borderRadius: '8px !important',
          '&:before': { display: 'none' },
        }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}>
            <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 700 }}>
              Input it received ({stage.input.length} chars)
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0 }}>
            <Typography variant="caption" sx={{
              whiteSpace: 'pre-wrap', color: '#94a3b8',
              fontFamily: '"JetBrains Mono", monospace', fontSize: '0.72rem',
            }}>
              {stage.input}
            </Typography>
          </AccordionDetails>
        </Accordion>
      )}

      {stage.output && (
        <Box sx={{ mt: 1.5, p: 1.5, borderRadius: 2, backgroundColor: 'rgba(15, 23, 42, 0.55)' }}>
          <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 700 }}>
            What it produced
          </Typography>
          <Box sx={{ mt: 0.5 }}>
            <AutoFormatDetectorRenderer content={stage.output} />
          </Box>
        </Box>
      )}

      {stage.error && (
        <Alert severity="error" sx={{ mt: 1.5, fontSize: '0.78rem' }}>
          {stage.error}
        </Alert>
      )}
    </Paper>
  );
}

export default function PlaygroundView({ state }) {
  const projectId = state?.projectId || null;
  const orgId = state?.orgId || null;

  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState('pipeline');      // 'pipeline' | 'agent'
  const [agents, setAgents] = useState([]);
  const [chosenAgent, setChosenAgent] = useState('');
  const [models, setModels] = useState([]);
  const [defaultModel, setDefaultModel] = useState(FALLBACK_DEFAULT_MODEL);
  const [chosenModel, setChosenModel] = useState('');   // '' = project default

  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState(null);
  const [intake, setIntake] = useState(null);
  const [plan, setPlan] = useState([]);
  const [unmatched, setUnmatched] = useState([]);
  const [pipeline, setPipeline] = useState(null);
  const [stages, setStages] = useState([]);
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState(null);
  const [runStartedAt, setRunStartedAt] = useState(null);
  const abortRef = useRef(null);
  const answerRef = useRef(null);

  // Runs are kept, so this is a place you return to, not a spinner you watch
  // once. Each finished run is saved whole (its plan, its agents, its answer)
  // per project; selecting one replays it read-only from the same state the
  // live stream fills, so nothing renders differently for a past run.
  const historyKey = projectId ? `agents_london_playground_${projectId}` : null;
  const [history, setHistory] = useState([]);
  const [viewingId, setViewingId] = useState(null);   // null = the live run
  const runRef = useRef(null);   // the run being assembled, saved when it ends
  const [detailOpen, setDetailOpen] = useState(false);   // the drill-down
  const [created, setCreated] = useState([]);   // agents made on the fly

  useEffect(() => {
    if (!historyKey) { setHistory([]); return; }
    try {
      const saved = JSON.parse(localStorage.getItem(historyKey) || '[]');
      setHistory(Array.isArray(saved) ? saved : []);
    } catch { setHistory([]); }
    setViewingId(null);
  }, [historyKey]);

  const persist = useCallback((next) => {
    setHistory(next);
    if (historyKey) {
      try { localStorage.setItem(historyKey, JSON.stringify(next.slice(0, 50))); }
      catch { /* a full disk should not break the run */ }
    }
  }, [historyKey]);

  useEffect(() => {
    let cancelled = false;
    fetchModels().then((catalogue) => {
      if (cancelled) return;
      setModels(chatModels(catalogue));
      setDefaultModel(catalogue.defaultModel);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!projectId) return undefined;
    let cancelled = false;
    (async () => {
      const { data } = await attempt(api.get(`/api/projects/${projectId}/agents`));
      if (cancelled || !data) return;
      // Only agents with a published version can be invoked by name (F.17).
      const invocable = (data.agents || []).filter((a) => a.mcp_tool);
      setAgents(invocable);
      if (invocable.length) setChosenAgent(invocable[0].mcp_tool);
    })();
    return () => { cancelled = true; };
  }, [projectId, orgId]);

  useEffect(() => {
    if (answer) answerRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [answer]);

  const reset = () => {
    setPhase(null); setIntake(null); setPlan([]); setUnmatched([]);
    setPipeline(null); setStages([]); setAnswer(null); setError(null);
    setCreated([]);
  };

  /** Fold one server event into the view. Nothing is added that did not arrive. */
  const onEvent = useCallback((name, data) => {
    const r = runRef.current;
    switch (name) {
      case 'accepted':
        setPhase('intake');
        break;

      case 'intake':
        setIntake(data);
        if (r) r.intake = data;
        setPhase('plan');
        break;

      case 'decomposed':
        setPlan(data.stages || []);
        if (r) r.plan = data.stages || [];
        setPhase('match');
        break;

      case 'matching':
        setStages((prev) => {
          const next = prev.some((s) => s.step === data.step) ? prev
            : [...prev, { step: data.step, need: data.need, status: 'matching' }];
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'matched':
        setStages((prev) => {
          const next = prev.map((s) => (s.step === data.step
            ? { ...s, ...data, status: 'pending' } : s));
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'unmatched':
        // Named, never dropped: a pipeline quietly missing a stage produces a
        // confident partial answer.
        setUnmatched((prev) => { const n = [...prev, data]; if (r) r.unmatched = n; return n; });
        setStages((prev) => { const n = prev.filter((s) => s.step !== data.step); if (r) r.stages = n; return n; });
        break;

      case 'published':
        setPipeline(data);
        if (r) r.pipeline = data;
        setPhase('run');
        break;

      case 'step_start':
        setStages((prev) => {
          const seeded = prev.some((s) => s.step === data.step)
            ? prev
            : [...prev, { step: data.step }];
          const next = seeded.map((s) => (s.step === data.step
            ? { ...s, ...data, status: 'running', startedAt: Date.now(), error: null }
            : s));
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'step_end':
        setStages((prev) => {
          const next = prev.map((s) => (s.step === data.step
            ? { ...s, ...data, status: data.failed ? 'failed' : 'done' } : s));
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'step_error':
        setStages((prev) => {
          const next = prev.map((s) => (s.step === data.step
            ? { ...s, status: 'failed', error: data.error, duration_ms: data.duration_ms }
            : s));
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'complete':
        setAnswer(data);
        if (r) r.answer = data;
        setPhase('answer');
        break;

      case 'materializing':
        // no registered agent fit this stage, so one is being created
        setStages((prev) => {
          const next = prev.some((s) => s.step === (data.step || data.need))
            ? prev
            : [...prev, { step: data.need, need: data.need, status: 'matching',
                          creating: true }];
          if (r) r.stages = next;
          return next;
        });
        break;

      case 'materialized':
        setCreated((prev) => prev.includes(data.agent_name || data.need)
          ? prev : [...prev, data.agent_name || data.need]);
        break;

      case 'materialize_failed':
      case 'materialize_pending':
        // left unmatched; the plan panel already names what went unstaffed
        break;

      case 'error':
        setError(typeof data.detail === 'string' ? data.detail : JSON.stringify(data));
        break;

      default:
        break;
    }
  }, []);

  const handleRun = async () => {
    if (!prompt.trim() || !projectId || running) return;
    reset();
    setViewingId(null);
    const asked = prompt.trim();
    runRef.current = {
      id: `run_${Date.now()}`, prompt: asked, at: Date.now(),
      mode, agent: mode === 'agent' ? chosenAgent : null,
      intake: null, plan: [], unmatched: [], pipeline: null,
      stages: [], answer: null,
    };
    setRunning(true);
    setRunStartedAt(Date.now());
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const runBody = mode === 'agent' && chosenAgent
        ? { prompt: asked, agent: chosenAgent }
        : { prompt: asked };
      if (chosenModel) runBody.model = chosenModel;
      await stream('/api/playground/stream', runBody, onEvent,
        { signal: controller.signal });
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.userMessage || e.message);
    } finally {
      setRunning(false);
      abortRef.current = null;
      // Keep the run if it reached an answer or ran any agent — an aborted
      // empty run is not worth a history slot.
      const r = runRef.current;
      if (r && (r.answer || r.stages.length)) {
        persist([{ ...r }, ...history.filter((h) => h.id !== r.id)]);
        setViewingId(r.id);
      }
    }
  };

  /** Show a saved run using the same panels the live stream fills. */
  const loadRun = (run) => {
    if (running) return;
    setViewingId(run.id);
    setIntake(run.intake); setPlan(run.plan || []);
    setUnmatched(run.unmatched || []); setPipeline(run.pipeline);
    setStages(run.stages || []); setAnswer(run.answer);
    setError(null); setPhase(run.answer ? 'answer' : 'run');
    setPrompt(run.prompt || '');
  };

  const newRun = () => {
    if (running) return;
    reset(); setViewingId(null); setPrompt('');
  };

  const deleteRun = (id, e) => {
    e?.stopPropagation();
    persist(history.filter((h) => h.id !== id));
    if (viewingId === id) newRun();
  };

  // The run currently on screen, assembled for the drill-down: a saved run if
  // one is selected, otherwise whatever the live stream has produced so far.
  const currentRun = useMemo(() => {
    if (viewingId) return history.find((h) => h.id === viewingId) || null;
    if (!answer && !stages.length) return null;
    return { id: 'live', prompt, at: runStartedAt || Date.now(),
             intake, plan, unmatched, pipeline, stages, answer };
  }, [viewingId, history, prompt, runStartedAt, intake, plan, unmatched,
      pipeline, stages, answer]);

  // Catalogue a proven combination as one reusable agent (Phase 5). The
  // composed pipeline is already published and pinned; this promotes it into
  // the agent registry so it is discoverable and A2A-invocable like any agent.
  const [cataloguing, setCataloguing] = useState(false);
  const onCatalogue = async (run) => {
    const tool = run?.pipeline?.mcp_tool || run?.answer?.mcp_tool;
    const pipelineId = run?.pipeline?.pipeline_id || run?.answer?.pipeline_id;
    if (!tool && !pipelineId) return;
    const name = window.prompt(
      'Name this combination as a reusable agent:',
      (run.prompt || 'Composed agent').slice(0, 60));
    if (!name) return;
    setCataloguing(true);
    const { data, error: err } = await attempt(api.post('/api/agents/catalogue-combination', {
      pipeline_id: pipelineId, mcp_tool: tool, name,
      goal: run.prompt || '', project_id: projectId, org_id: orgId,
      stages: (run.stages || []).map((s) => ({
        step: s.step, agent_name: s.agent_name,
        version: s.version, content_hash: s.content_hash })),
    }));
    setCataloguing(false);
    if (err || !data?.ok) {
      setError((err && (err.userMessage || err.message)) || data?.detail
               || 'Could not catalogue this combination.');
      return;
    }
    setError(null);
    setDetailOpen(false);
    setCatalogued({ name, agent_id: data.agent_id });
  };
  const [catalogued, setCatalogued] = useState(null);

  const handleStop = () => {
    abortRef.current?.abort();
    setRunning(false);
    // Whatever had already happened stays on screen; stopping the stream does
    // not un-run the agents that already ran.
    setError('Stopped watching. Stages that had already started continued on the server.');
  };

  const phaseIndex = useMemo(
    () => PHASES.findIndex((p) => p.key === phase), [phase]);

  const canRun = Boolean(prompt.trim()) && Boolean(projectId) && !running;

  return (
    <Box sx={{ display: 'flex', height: '100%', minHeight: 0 }}>
      {/* Runs kept: a place you return to, not a spinner watched once. */}
      <Paper elevation={0} sx={{
        width: { xs: 0, md: 260 }, display: { xs: 'none', md: 'flex' },
        flexDirection: 'column', borderRight: '1px solid rgba(255,255,255,0.08)',
        bgcolor: 'rgba(9, 13, 22, 0.5)', overflow: 'hidden',
      }}>
        <Box sx={{ p: 1.5 }}>
          <Button fullWidth variant="outlined" size="small"
                  onClick={newRun} disabled={running}
                  startIcon={<PlayArrowIcon sx={{ fontSize: 14 }} />}>
            New run
          </Button>
        </Box>
        <Divider sx={{ borderColor: 'rgba(255,255,255,0.06)' }} />
        <Box sx={{ flex: 1, overflowY: 'auto', p: 1 }}>
          {history.length === 0 && (
            <Typography variant="caption" sx={{ color: '#64748b', px: 1 }}>
              No runs yet. Give the civilisation a goal and it will keep the
              whole run here — plan, agents, answer.
            </Typography>
          )}
          {history.map((h) => {
            const active = viewingId === h.id;
            return (
              <Paper key={h.id} elevation={0} onClick={() => loadRun(h)}
                sx={{
                  p: 1, mb: 0.75, cursor: 'pointer', borderRadius: 1.5,
                  bgcolor: active ? 'rgba(56,189,248,0.12)' : 'transparent',
                  border: `1px solid ${active ? 'rgba(56,189,248,0.4)' : 'rgba(255,255,255,0.06)'}`,
                  '&:hover': { bgcolor: 'rgba(56,189,248,0.08)' },
                }}>
                <Stack direction="row" alignItems="flex-start" spacing={0.5}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="caption" sx={{
                      color: '#e2e8f0', fontWeight: 600, display: '-webkit-box',
                      WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }}>
                      {h.prompt || '(untitled run)'}
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 0.25 }}>
                      {h.answer?.failed ? 'halted' : h.answer?.refused ? 'refused'
                        : `${(h.stages || []).length} stage${(h.stages || []).length === 1 ? '' : 's'}`}
                      {' · '}{new Date(h.at).toLocaleTimeString()}
                    </Typography>
                  </Box>
                  <IconButton size="small" onClick={(e) => deleteRun(h.id, e)}
                              sx={{ p: 0.25, color: '#475569' }}>
                    <StopIcon sx={{ fontSize: 13 }} />
                  </IconButton>
                </Stack>
              </Paper>
            );
          })}
        </Box>
      </Paper>

    <Box sx={{ flex: 1, p: 3, display: 'flex', flexDirection: 'column', gap: 2.5, height: '100%', overflowY: 'auto' }}>
      {viewingId && !running && (
        <Alert severity="info" icon={false} sx={{ fontSize: '0.78rem' }}
               action={<Button size="small" onClick={newRun}>New run</Button>}>
          Viewing a saved run. Start a new run to compose again.
        </Alert>
      )}
      {/* The ask */}
      <Paper sx={{ p: 2.5, borderRadius: 3, bgcolor: 'rgba(15, 23, 42, 0.75)' }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={2}>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Playground</Typography>
            <Typography variant="caption" color="text.secondary">
              A goal becomes a pipeline of published agents, and you watch it run.
              Project <code>{projectId || '—'}</code>
            </Typography>
          </Box>

          <Stack direction="row" spacing={1.5} alignItems="center">
            <ToggleButtonGroup value={mode} exclusive size="small" color="primary"
                               onChange={(e, value) => value && setMode(value)}>
              <ToggleButton value="pipeline">
                <AccountTreeIcon sx={{ mr: 0.8, fontSize: 16 }} /> Compose a pipeline
              </ToggleButton>
              <ToggleButton value="agent">
                <PersonSearchIcon sx={{ mr: 0.8, fontSize: 16 }} /> One agent
              </ToggleButton>
            </ToggleButtonGroup>

            {mode === 'agent' && (
              <FormControl size="small" sx={{ minWidth: 220 }}>
                <InputLabel>Published agent</InputLabel>
                <Select value={chosenAgent} label="Published agent"
                        onChange={(e) => setChosenAgent(e.target.value)}>
                  {agents.map((a) => (
                    <MenuItem key={a.mcp_tool} value={a.mcp_tool}>
                      {a.name} — v{a.version}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}

            {mode === 'pipeline' && models.length > 0 && (
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel>Model</InputLabel>
                <Select value={chosenModel} label="Model"
                        onChange={(e) => setChosenModel(e.target.value)}>
                  <MenuItem value=""><em>Project default ({defaultModel})</em></MenuItem>
                  {models.map((m) => (
                    <MenuItem key={m.id} value={m.id}>{m.name || m.id}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}
          </Stack>
        </Stack>

        <Stack direction="row" spacing={1.5} sx={{ mt: 2 }} alignItems="flex-start">
          <TextField
            fullWidth multiline maxRows={4} size="small"
            placeholder="Describe what you want done — e.g. “Research our top three competitors, compare their pricing, and write a one-page memo.”"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleRun();
            }}
          />
          {running ? (
            <Button variant="outlined" color="warning" startIcon={<StopIcon />}
                    onClick={handleStop} sx={{ px: 3, whiteSpace: 'nowrap' }}>
              Stop watching
            </Button>
          ) : (
            <Button variant="contained" endIcon={<PlayArrowIcon />}
                    onClick={handleRun} disabled={!canRun} sx={{ px: 3, whiteSpace: 'nowrap' }}>
              Run
            </Button>
          )}
        </Stack>

        {mode === 'agent' && agents.length === 0 && (
          <Alert severity="info" sx={{ mt: 1.5, fontSize: '0.78rem' }}>
            No agent in this project has a published version yet, so none can be
            invoked by name. Compose a pipeline instead, or publish an agent.
          </Alert>
        )}
        {models.length > 0 && (
          <Typography variant="caption" sx={{ color: '#64748b', mt: 1, display: 'block' }}>
            {chosenModel
              ? <>Planning and any agents created on the fly will run on{' '}
                  <strong>{chosenModel}</strong>; a pre-existing published agent
                  keeps its version-pinned model.</>
              : <>Agents run on the model their published version declares; the
                  project default is <strong>{defaultModel}</strong>. Pick a
                  model to override it for this run.</>}
          </Typography>
        )}
      </Paper>

      {/* Where it has got to */}
      {(running || phase) && (
        <Paper sx={{ p: 2, borderRadius: 3, bgcolor: 'rgba(15, 23, 42, 0.6)' }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {PHASES.map((p, index) => {
              const reached = phaseIndex >= index;
              const current = phase === p.key && running;
              return (
                <Tooltip key={p.key} title={p.hint}>
                  <Chip
                    size="small"
                    label={p.label}
                    color={reached ? 'primary' : 'default'}
                    variant={current ? 'filled' : reached ? 'outlined' : 'outlined'}
                    icon={current ? <CircularProgress size={12} color="inherit" /> : undefined}
                    sx={{ fontWeight: current ? 800 : 600,
                          opacity: reached ? 1 : 0.45 }}
                  />
                </Tooltip>
              );
            })}
            {running && runStartedAt && (
              <Typography variant="caption" sx={{ color: '#94a3b8', ml: 'auto' }}>
                <Elapsed since={runStartedAt} /> elapsed
              </Typography>
            )}
          </Stack>
          {running && <LinearProgress sx={{ mt: 1.5, borderRadius: 1 }} />}
        </Paper>
      )}

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

      {/* What the Intake Praetor decided */}
      {intake && (
        <Paper sx={{ p: 2, borderRadius: 3, bgcolor: 'rgba(15, 23, 42, 0.6)' }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#38bdf8' }}>
              The Intake Praetor
            </Typography>
            <Chip size="small" label={intake.route} color="secondary"
                  sx={{ height: 18, fontSize: '0.62rem', fontWeight: 700 }} />
            {intake.confidence && (
              <Chip size="small" variant="outlined"
                    label={`confidence: ${intake.confidence}`}
                    color={intake.confidence === 'low' ? 'warning' : 'default'}
                    sx={{ height: 18, fontSize: '0.62rem' }} />
            )}
            {intake.retrieved != null && (
              <Chip size="small" variant="outlined"
                    label={intake.retrieved ? 'retrieved first' : 'no retrieval'}
                    sx={{ height: 18, fontSize: '0.62rem' }} />
            )}
          </Stack>
          {intake.reasoning && (
            <Typography variant="body2" sx={{ color: '#cbd5e1', mt: 0.75 }}>
              {intake.reasoning}
            </Typography>
          )}
        </Paper>
      )}

      {/* The plan, and what could not be staffed */}
      {plan.length > 0 && (
        <Paper sx={{ p: 2, borderRadius: 3, bgcolor: 'rgba(15, 23, 42, 0.6)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#38bdf8', mb: 1 }}>
            Plan — {plan.length} stage{plan.length === 1 ? '' : 's'}
          </Typography>
          <Stack spacing={0.5}>
            {plan.map((s, i) => (
              <Typography key={s.step} variant="caption" sx={{ color: '#94a3b8' }}>
                {i + 1}. <strong style={{ color: '#e2e8f0' }}>{s.step}</strong> — {s.need}
              </Typography>
            ))}
          </Stack>
          {unmatched.length > 0 && (
            <Alert severity="warning" sx={{ mt: 1.5, fontSize: '0.78rem' }}>
              {unmatched.length} stage{unmatched.length === 1 ? '' : 's'} had no
              registered agent and {unmatched.length === 1 ? 'was' : 'were'} left
              out: {unmatched.map((s) => s.need).join('; ')}
            </Alert>
          )}
        </Paper>
      )}

      {created.length > 0 && (
        <Alert severity="info" sx={{ fontSize: '0.8rem' }}>
          {created.length} agent{created.length === 1 ? '' : 's'} created on the
          fly for stages no registered agent could staff:{' '}
          <strong>{created.join(', ')}</strong>. They are now registered and
          reusable.
        </Alert>
      )}

      {/* The published composition */}
      {pipeline && (
        <Paper sx={{ p: 2, borderRadius: 3, bgcolor: 'rgba(16, 185, 129, 0.06)',
                     border: '1px solid rgba(16, 185, 129, 0.25)' }}>
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#10b981' }}>
              Published and pinned
            </Typography>
            <Typography variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#93c5fd' }}>
              {pipeline.mcp_tool}
            </Typography>
            <Tooltip title="Copy the name this pipeline is invoked by">
              <IconButton size="small"
                          onClick={() => navigator.clipboard?.writeText(pipeline.mcp_tool)}>
                <ContentCopyIcon sx={{ fontSize: 14 }} />
              </IconButton>
            </Tooltip>
            {pipeline.is_cyclic && (
              <Chip size="small" color="warning" label="cyclic"
                    sx={{ height: 18, fontSize: '0.62rem' }} />
            )}
          </Stack>
          <Typography variant="caption" sx={{ color: '#94a3b8' }}>
            The registry validated the wiring between every stage and pinned each
            one to an exact version before anything ran.
          </Typography>
        </Paper>
      )}

      {/* The agents at work */}
      {stages.length > 0 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#38bdf8' }}>
            Agents at work
          </Typography>
          {stages.map((stage) => <StageCard key={stage.step} stage={stage} />)}
        </Box>
      )}

      {/* What was asked for */}
      {answer && (
        <Paper ref={answerRef} sx={{
          p: 3, borderRadius: 3,
          bgcolor: answer.failed ? 'rgba(239, 68, 68, 0.06)' : 'rgba(15, 23, 42, 0.85)',
          border: `1px solid ${answer.failed ? 'rgba(239,68,68,0.3)' : 'rgba(56,189,248,0.25)'}`,
        }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700,
                                                  color: answer.failed ? '#f87171' : '#38bdf8' }}>
              {answer.failed ? 'The run halted' : answer.refused ? 'Refused' : 'Answer'}
            </Typography>
            <Stack direction="row" spacing={1.5} alignItems="center">
              {answer.stages_run != null && (
                <Typography variant="caption" sx={{ color: '#94a3b8' }}>
                  {answer.stages_run} stage{answer.stages_run === 1 ? '' : 's'}
                </Typography>
              )}
              {answer.duration_ms != null && (
                <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 700 }}>
                  {(answer.duration_ms / 1000).toFixed(1)}s total
                </Typography>
              )}
              {!answer.failed && !answer.refused && (stages.length > 0 || answer.direct) && (
                <Button size="small" variant="outlined"
                        startIcon={<AccountTreeOutlinedIcon sx={{ fontSize: 15 }} />}
                        onClick={() => setDetailOpen(true)}>
                  How this was built
                </Button>
              )}
            </Stack>
          </Stack>

          <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,0.08)' }} />

          {answer.failed ? (
            <Alert severity="error">
              Halted at <strong>{answer.halted_at}</strong>. {answer.reason}
              <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                The stages before it did run, and their output is above. There is
                no final deliverable, because the pipeline did not finish.
              </Typography>
            </Alert>
          ) : (
            <AutoFormatDetectorRenderer content={answer.answer} />
          )}

          {answer.direct && (
            <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 1.5 }}>
              Answered at intake — no pipeline was composed, because none was needed.
            </Typography>
          )}
        </Paper>
      )}

      {!running && !phase && (
        <Paper sx={{ p: 4, borderRadius: 3, bgcolor: 'rgba(15, 23, 42, 0.4)', textAlign: 'center' }}>
          <Typography variant="body2" sx={{ color: '#94a3b8' }}>
            Give the civilisation a goal. You will see which founder routes it,
            how it is broken into stages, which published agent is matched to
            each, the pipeline being pinned — and then each agent running, on the
            output of the one before it.
          </Typography>
        </Paper>
      )}

      {catalogued && (
        <Alert severity="success" onClose={() => setCatalogued(null)}
               sx={{ fontSize: '0.82rem' }}>
          Catalogued <strong>{catalogued.name}</strong> as a reusable agent. It
          is now in the Agent Registry and can be composed into future
          pipelines like any other agent.
        </Alert>
      )}
    </Box>

    <RunDetailModal run={currentRun} open={detailOpen}
                    onClose={() => setDetailOpen(false)}
                    onCatalogue={cataloguing ? undefined : onCatalogue} />
    </Box>
  );
}
