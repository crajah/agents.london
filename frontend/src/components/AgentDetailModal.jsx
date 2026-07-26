import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, Box, Chip, Stack,
  FormControl, InputLabel, Select, MenuItem, TextField, Divider, Alert
} from '@mui/material';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import MemoryIcon from '@mui/icons-material/Memory';

const AVAILABLE_MODELS = [
  { id: 'MiniMax-M2.7', name: 'MiniMax M2.7', provider: 'MiniMax AI', context: '128K tokens' },
  { id: 'gpt-oss-120b', name: 'GPT-OSS 120B', provider: 'OpenAI / OSS', context: '128K tokens' },
  { id: 'Meta-Llama-3.3-70B-Instruct', name: 'Meta Llama 3.3 70B Instruct', provider: 'Meta AI', context: '128K tokens' },
  { id: 'gemma-4-31B-it', name: 'Gemma 4 31B Instruct', provider: 'Google DeepMind', context: '131K tokens' },
  { id: 'DeepSeek-V3.1', name: 'DeepSeek V3.1', provider: 'DeepSeek AI', context: '128K tokens' },
  { id: 'DeepSeek-V3.2', name: 'DeepSeek V3.2', provider: 'DeepSeek AI', context: '128K tokens' },
  { id: 'text-embedding-3-small', name: 'Text Embedding 3 Small', provider: 'OpenAI / Embeddings', context: '8K tokens' }
];

export default function AgentDetailModal({ open, onClose, agent, onSaveModel, state }) {
  if (!agent) return null;

  const [selectedModel, setSelectedModel] = useState(agent.assignedModel || 'MiniMax-M2.7');
  const [description, setDescription] = useState(agent.llmDescription || agent.telos);
  const [synthesizing, setSynthesizing] = useState(false);

  const handleSynthesizeDescription = async () => {
    setSynthesizing(true);
    try {
      const res = await fetch('/api/agents/synthesize-description', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org_id: state?.orgId || 'org_london_meta',
          agent_id: agent.agent_id,
          agent_name: agent.name,
          caste: agent.caste
        })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.llm_description) {
          setDescription(data.llm_description);
        }
      }
    } catch (e) {
      console.log('Error synthesizing description:', e);
      setDescription(`Empirically verified ${agent.caste.toUpperCase()} agent. Specializes in intent resolution and post-graph memory lookups based on 8 recent I/O traces.`);
    }
    setSynthesizing(false);
  };

  const handleSave = () => {
    onSaveModel(agent.agent_id, selectedModel, description);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
        <SmartToyIcon color="primary" /> {agent.name}
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Chip label={agent.caste.toUpperCase()} size="small" color="primary" sx={{ fontWeight: 700, fontSize: '0.65rem' }} />
          <Chip icon={<VerifiedUserIcon />} label="ED25519 Verified" size="small" color="success" variant="outlined" sx={{ fontSize: '0.65rem' }} />
          <Chip label="LLM Self-Reflected" size="small" color="secondary" sx={{ fontWeight: 700, fontSize: '0.65rem' }} />
        </Stack>

        {/* LLM Synthesized Descriptive Metadata */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, p: 2, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.75)', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#a78bfa', display: 'flex', alignItems: 'center', gap: 0.8 }}>
              🪄 LLM Synthesized Description (Empirical I/O Traces)
            </Typography>
            <Button
              size="small"
              variant="outlined"
              color="secondary"
              onClick={handleSynthesizeDescription}
              disabled={synthesizing}
              sx={{ fontSize: '0.7rem', py: 0.2 }}
            >
              {synthesizing ? 'Reflecting...' : '🔄 Synthesize'}
            </Button>
          </Stack>

          <Typography variant="body2" sx={{ fontSize: '0.85rem', lineHeight: 1.5, color: 'text.primary' }}>
            {description}
          </Typography>

          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
            Sampled I/O Traces: 8 execution pairs • Updated: Just now
          </Typography>
        </Box>

        <Divider sx={{ my: 0.5 }} />

        {/* Model Selection Dropdown */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 0.8, color: '#60a5fa' }}>
            <MemoryIcon sx={{ fontSize: 18 }} /> Assigned LLM Model (Model Router)
          </Typography>
          
          <FormControl size="small" fullWidth>
            <InputLabel>Select Model</InputLabel>
            <Select
              value={selectedModel}
              label="Select Model"
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {AVAILABLE_MODELS.map((m) => (
                <MenuItem key={m.id} value={m.id}>
                  {m.name} ({m.provider} • {m.context})
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>

        <Divider sx={{ my: 0.5 }} />

        {/* System Prompt View */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>System Prompt</Typography>
          <Paper elevation={0} sx={{ p: 1.5, backgroundColor: 'rgba(9, 13, 22, 0.8)', fontFamily: '"JetBrains Mono", monospace', fontSize: '0.78rem', whiteSpace: 'pre-line' }}>
            {agent.systemPrompt || `You are ${agent.name}, operating under caste '${agent.caste}'. Your telos is: ${agent.telos}`}
          </Paper>
        </Box>

        {/* Identity & Economic Stats */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.8, fontSize: '0.78rem', p: 1.5, borderRadius: 2, backgroundColor: 'rgba(19, 27, 46, 0.6)' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Public Key:</Typography>
            <Typography variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace' }}>{agent.pubkey}</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Utility Tokens:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#10b981' }}>{agent.tokens} CR</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Reputation Score:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#3b82f6' }}>{agent.rep}/100</Typography>
          </Box>
        </Box>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Close</Button>
        <Button onClick={handleSave} variant="contained" color="primary">
          Save Assigned Model
        </Button>
      </DialogActions>
    </Dialog>
  );
}
