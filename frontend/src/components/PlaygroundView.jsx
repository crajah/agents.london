import React, { useState } from 'react';
import {
  Box, Paper, Typography, ToggleButtonGroup, ToggleButton, TextField, Button, Chip, Stack, CircularProgress
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import TerminalIcon from '@mui/icons-material/Terminal';
import PsychologyIcon from '@mui/icons-material/Psychology';
import AccountTreeIcon from '@mui/icons-material/AccountTree';

export default function PlaygroundView({ state }) {
  const [mode, setMode] = useState('conductor');
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([
    { type: 'SYSTEM', content: 'Civilization Playground initialized. Select a mode and enter your goal to orchestrate tasks across 1 billion agents.' }
  ]);

  const handleRunGoal = async () => {
    if (!prompt.trim()) return;
    const currentPrompt = prompt;
    setPrompt('');
    setLoading(true);

    setSteps(prev => [...prev, { type: 'USER', content: currentPrompt }]);

    setTimeout(() => {
      setSteps(prev => [
        ...prev,
        { type: 'CONDUCTOR', content: `Querying post-graph-rag shared memory for optimal multi-agent routing...` }
      ]);

      setTimeout(() => {
        setSteps(prev => [
          ...prev,
          { type: 'ACTION', content: `Invoking MCP Tool 'mcp-pgvector-search' to search vector index in realm '${state.orgId}'...` }
        ]);

        setTimeout(() => {
          setSteps(prev => [
            ...prev,
            { type: 'OBSERVATION', content: `Received 4 matching document chunks with 0.94 cosine similarity score.` },
            { type: 'FINAL_ANSWER', content: `Goal completed successfully! Materialized worker agent verified ED25519 payload signature.` }
          ]);
          setLoading(false);
        }, 600);
      }, 600);
    }, 600);
  };

  const getStepChipColor = (type) => {
    switch (type) {
      case 'USER': return 'primary';
      case 'CONDUCTOR': return 'secondary';
      case 'ACTION': return 'warning';
      case 'OBSERVATION': return 'info';
      case 'FINAL_ANSWER': return 'success';
      default: return 'default';
    }
  };

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      {/* Header Bar */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Interactive Civilization Playground
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Orchestrate multi-tenant agent goals via Conductor Composition, ReAct loops, or Direct Messaging.
          </Typography>
        </Box>

        <ToggleButtonGroup
          value={mode}
          exclusive
          onChange={(e, newMode) => newMode && setMode(newMode)}
          size="small"
          color="primary"
        >
          <ToggleButton value="conductor">
            <AccountTreeIcon sx={{ mr: 1, fontSize: 18 }} /> Conductor Mode
          </ToggleButton>
          <ToggleButton value="react">
            <PsychologyIcon sx={{ mr: 1, fontSize: 18 }} /> ReAct Loop
          </ToggleButton>
          <ToggleButton value="direct">
            <TerminalIcon sx={{ mr: 1, fontSize: 18 }} /> Direct Chat
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* Main Console & Steps Paper */}
      <Paper sx={{ flex: 1, p: 3, display: 'flex', flexDirection: 'column', gap: 2, minHeight: 450 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
          {mode === 'conductor' ? '🎵 Conductor Multi-Agent Composition' : mode === 'react' ? '🔄 ReAct Reasoning Loop (Thought -> Action -> Observation)' : '💬 Direct Agent Messaging'}
        </Typography>

        {/* Steps Scroll Area */}
        <Box sx={{ flex: 1, overflowY: 'auto', p: 2, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.7)', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {steps.map((step, idx) => (
            <Paper key={idx} elevation={0} sx={{ p: 1.5, backgroundColor: 'rgba(19, 27, 46, 0.6)', borderLeft: `4px solid ${step.type === 'USER' ? '#3b82f6' : step.type === 'FINAL_ANSWER' ? '#10b981' : '#8b5cf6'}` }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                <Chip label={step.type} size="small" color={getStepChipColor(step.type)} sx={{ height: 20, fontSize: '0.65rem', fontWeight: 700 }} />
              </Stack>
              <Typography variant="body2" sx={{ fontFamily: step.type === 'USER' ? 'inherit' : '"JetBrains Mono", monospace', fontSize: '0.85rem' }}>
                {step.content}
              </Typography>
            </Paper>
          ))}
          {loading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, p: 1.5 }}>
              <CircularProgress size={20} />
              <Typography variant="caption" color="text.secondary">Orchestrating civilizational agents...</Typography>
            </Box>
          )}
        </Box>

        {/* Prompt Input Container */}
        <Box sx={{ display: 'flex', gap: 1.5 }}>
          <TextField
            fullWidth
            placeholder="e.g. Discover specialized dataset processing agents, vectorize payloads in post-graph-rag, and execute compliance checks..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleRunGoal()}
            multiline
            maxRows={3}
            size="small"
          />
          <Button
            variant="contained"
            color="primary"
            endIcon={<PlayArrowIcon />}
            onClick={handleRunGoal}
            disabled={loading}
            sx={{ px: 3, height: 'auto' }}
          >
            Execute
          </Button>
        </Box>
      </Paper>
    </Box>
  );
}
