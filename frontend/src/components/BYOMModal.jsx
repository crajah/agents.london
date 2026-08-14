import React, { useState } from 'react';
import { api, attempt } from '../utils/api';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, FormControl, InputLabel, Select, MenuItem, Box, Typography, Alert, Stack, Chip
} from '@mui/material';
import KeyIcon from '@mui/icons-material/Key';
import StorageIcon from '@mui/icons-material/Storage';

export default function BYOMModal({ open, onClose, state, onAddCustomModel }) {
  const [scope, setScope] = useState('user');
  const [provider, setProvider] = useState('OpenAI');
  const [customModelId, setCustomModelId] = useState('');
  const [apiEndpoint, setApiEndpoint] = useState('https://api.openai.com/v1');
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');

  const handleSubmit = async () => {
    if (!customModelId.trim() || !apiKey.trim()) return;
    setLoading(true);

    const payload = {
      org_id: state.orgId,
      user_id: state.userId,
      project_id: state.projectId,
      scope_level: scope,
      provider_name: provider,
      custom_model_id: customModelId.trim(),
      api_endpoint: apiEndpoint.trim(),
      api_key: apiKey.trim()
    };

    try {
      const res = await api.post('/api/models/custom', payload);

      {
        setSuccessMsg(`Successfully saved BYOM & BYOK model '${customModelId}' to post-graph DB at '${scope}' scope!`);
      }
    } catch (e) {
      console.log('Error saving to post-graph backend:', e);
    }

    onAddCustomModel({
      id: customModelId.trim(),
      name: `${customModelId.trim()} (${provider} • ${scope.toUpperCase()})`,
      provider: provider,
      context_window: 128000,
      status: 'active',
      scope: scope
    });

    setLoading(false);
    setTimeout(() => {
      setSuccessMsg('');
      setCustomModelId('');
      setApiKey('');
      onClose();
    }, 1200);
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
        <KeyIcon color="primary" /> Bring Your Own Model (BYOM) & API Key (BYOK)
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <Alert severity="info" sx={{ fontSize: '0.8rem' }}>
          Configure custom LLMs and secret API keys scoped to Organization, Project, or User. Encrypted & persisted in <strong>post-graph</strong> graph database.
        </Alert>

        {successMsg && <Alert severity="success">{successMsg}</Alert>}

        {/* Scope Selection */}
        <FormControl size="small" fullWidth>
          <InputLabel>Configuration Hierarchy Scope</InputLabel>
          <Select
            value={scope}
            label="Configuration Hierarchy Scope"
            onChange={(e) => setScope(e.target.value)}
          >
            <MenuItem value="user">User Level Scope ({state.userId})</MenuItem>
            <MenuItem value="project">Project Universe Scope ({state.projectId})</MenuItem>
            <MenuItem value="org">Organization Realm Scope ({state.orgId})</MenuItem>
          </Select>
        </FormControl>

        {/* Provider Selection */}
        <FormControl size="small" fullWidth>
          <InputLabel>LLM Provider / Backend</InputLabel>
          <Select
            value={provider}
            label="LLM Provider / Backend"
            onChange={(e) => {
              const p = e.target.value;
              setProvider(p);
              if (p === 'OpenAI') setApiEndpoint('https://api.openai.com/v1');
              else if (p === 'Anthropic') setApiEndpoint('https://api.anthropic.com/v1');
              else if (p === 'Groq') setApiEndpoint('https://api.groq.com/openai/v1');
              else if (p === 'Ollama') setApiEndpoint('http://localhost:11434/v1');
            }}
          >
            <MenuItem value="OpenAI">OpenAI</MenuItem>
            <MenuItem value="Anthropic">Anthropic</MenuItem>
            <MenuItem value="Groq">Groq AI</MenuItem>
            <MenuItem value="Together">Together AI</MenuItem>
            <MenuItem value="Ollama">Ollama (Local / On-Prem)</MenuItem>
            <MenuItem value="Custom">Custom OpenAI-Compatible Proxy</MenuItem>
          </Select>
        </FormControl>

        {/* Custom Model ID */}
        <TextField
          label="Model ID / Identifier"
          size="small"
          fullWidth
          placeholder="e.g. gpt-4o-mini, claude-3-5-sonnet, llama-3.3-70b-versatile"
          value={customModelId}
          onChange={(e) => setCustomModelId(e.target.value)}
        />

        {/* API Base Endpoint */}
        <TextField
          label="API Base Endpoint URL"
          size="small"
          fullWidth
          value={apiEndpoint}
          onChange={(e) => setApiEndpoint(e.target.value)}
        />

        {/* Secret API Key */}
        <TextField
          label="Secret API Key (BYOK)"
          size="small"
          type="password"
          fullWidth
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.7)', fontSize: '0.75rem', color: 'text.secondary' }}>
          <StorageIcon sx={{ fontSize: 16, color: '#60a5fa' }} />
          <span>Storage Target: <strong>post-graph</strong> PostgreSQL Vertex Table <code>custom_model_configs</code></span>
        </Box>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          color="primary"
          disabled={loading || !customModelId.trim() || !apiKey.trim()}
        >
          {loading ? 'Persisting to post-graph DB...' : 'Save Model & Key to post-graph'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
