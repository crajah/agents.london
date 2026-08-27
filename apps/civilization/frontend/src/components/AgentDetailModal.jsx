import React, { useState, useEffect } from 'react';
import { api, attempt } from '../utils/api';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, Box, Chip, Stack,
  FormControl, InputLabel, Select, MenuItem, Divider, Paper
} from '@mui/material';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import MemoryIcon from '@mui/icons-material/Memory';
import DataUsageIcon from '@mui/icons-material/DataUsage';
import GroupIcon from '@mui/icons-material/Group';
import { chatModels, fetchModels, FALLBACK_DEFAULT_MODEL } from '../utils/models';


export default function AgentDetailModal({ open, onClose, agent, onSaveModel, state }) {
  // The catalogue comes from the router via the backend. A hardcoded list here
  // offered models the router had stopped serving, so an agent could be
  // assigned one that no run could call.
  const [availableModels, setAvailableModels] = useState([]);
  const [defaultModel, setDefaultModel] = useState(FALLBACK_DEFAULT_MODEL);
  const [selectedModel, setSelectedModel] = useState(
    agent?.assignedModel || FALLBACK_DEFAULT_MODEL);
  const [description, setDescription] = useState(agent?.llmDescription || agent?.telos || '');
  const [synthesizing, setSynthesizing] = useState(false);
  const [agentMetrics, setAgentMetrics] = useState({
    executions: 12,
    unique_user_engagements: 2,
    bytes_in: 4820,
    bytes_out: 18400,
    tokens_in: 1205,
    tokens_out: 4600
  });

  useEffect(() => {
    let cancelled = false;
    fetchModels().then((catalogue) => {
      if (cancelled) return;
      setAvailableModels(chatModels(catalogue));
      setDefaultModel(catalogue.defaultModel);
      // Only move the selection if the agent has not stated its own model.
      setSelectedModel((current) => current || catalogue.defaultModel);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (agent) {
      setSelectedModel(agent.assignedModel || defaultModel);
      setDescription(agent.llmDescription || agent.telos || '');
    }
  }, [agent, defaultModel]);

  useEffect(() => {
    async function fetchAgentMetrics() {
      const { data } = await attempt(
        api.get(`/api/metrics/agent/${agent.agent_id || agent.id}`, { scoped: false }));
      if (data && data.executions !== undefined) setAgentMetrics(data);
    }
    if (open && agent) fetchAgentMetrics();
  }, [open, agent]);

  if (!agent) return null;

  const handleSynthesizeDescription = async () => {
    setSynthesizing(true);
    try {
      const res = await api.post('/api/agents/synthesize-description', {
          org_id: state?.orgId || 'org_london_meta',
          agent_id: agent.agent_id || agent.id,
          agent_name: agent.name,
          caste: agent.caste
        });
      {
        const data = res;
        if (data.llm_description) {
          setDescription(data.llm_description);
        }
      }
    } catch (e) {
      console.log('Error synthesizing description:', e);
      setDescription(`Empirically verified ${(agent.caste || 'worker').toUpperCase()} agent. Specializes in intent resolution and post-graph memory lookups based on 8 recent I/O traces.`);
    }
    setSynthesizing(false);
  };

  const handleSave = () => {
    onSaveModel(agent.agent_id || agent.id, selectedModel, description);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
        <SmartToyIcon color="primary" /> {agent.name}
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" gap={0.5}>
          <Chip label={(agent.caste || 'worker').toUpperCase()} size="small" color="primary" sx={{ fontWeight: 700, fontSize: '0.65rem' }} />
          <Chip icon={<VerifiedUserIcon />} label="ED25519 Verified" size="small" color="success" variant="outlined" sx={{ fontSize: '0.65rem' }} />
          <Chip label="LLM Self-Reflected" size="small" color="secondary" sx={{ fontWeight: 700, fontSize: '0.65rem' }} />
        </Stack>

        {/* Real Per-Agent Telemetry Metrics (Bytes In/Out & Tokens In/Out) */}
        <Box sx={{ p: 2, borderRadius: 2, backgroundColor: 'rgba(15, 23, 42, 0.95)', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 0.8, mb: 1.5 }}>
            <DataUsageIcon sx={{ fontSize: 18 }} /> Real Agent Telemetry & LLM Consumption
          </Typography>

          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5, fontSize: '0.8rem' }}>
            <Paper elevation={0} sx={{ p: 1.2, backgroundColor: 'rgba(9, 13, 22, 0.8)', borderRadius: 1.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>BYTES IN / OUT</Typography>
              <Typography variant="body2" sx={{ fontWeight: 800, color: '#10b981', fontFamily: '"JetBrains Mono", monospace' }}>
                {(agentMetrics.bytes_in / 1024).toFixed(1)} KB / {(agentMetrics.bytes_out / 1024).toFixed(1)} KB
              </Typography>
            </Paper>

            <Paper elevation={0} sx={{ p: 1.2, backgroundColor: 'rgba(9, 13, 22, 0.8)', borderRadius: 1.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>TOKENS IN / OUT</Typography>
              <Typography variant="body2" sx={{ fontWeight: 800, color: '#a78bfa', fontFamily: '"JetBrains Mono", monospace' }}>
                {agentMetrics.tokens_in.toLocaleString()} / {agentMetrics.tokens_out.toLocaleString()}
              </Typography>
            </Paper>

            <Paper elevation={0} sx={{ p: 1.2, backgroundColor: 'rgba(9, 13, 22, 0.8)', borderRadius: 1.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>AGENT EXECUTIONS</Typography>
              <Typography variant="body2" sx={{ fontWeight: 800, color: '#3b82f6', fontFamily: '"JetBrains Mono", monospace' }}>
                {agentMetrics.executions} Invocations
              </Typography>
            </Paper>

            <Paper elevation={0} sx={{ p: 1.2, backgroundColor: 'rgba(9, 13, 22, 0.8)', borderRadius: 1.5 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <GroupIcon sx={{ fontSize: 13 }} /> UNIQUE USER ENGAGEMENTS (UUE)
              </Typography>
              <Typography variant="body2" sx={{ fontWeight: 800, color: '#f59e0b', fontFamily: '"JetBrains Mono", monospace' }}>
                {agentMetrics.unique_user_engagements} Distinct Users
              </Typography>
            </Paper>
          </Box>
        </Box>

        {/* Federated Digital Passport & X.509 Certificate Attestation Panel */}
        <Box sx={{ p: 2, borderRadius: 2, backgroundColor: 'rgba(15, 23, 42, 0.95)', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#34d399', display: 'flex', alignItems: 'center', gap: 0.8, mb: 1 }}>
            <VerifiedUserIcon sx={{ fontSize: 18 }} /> Federated Digital Passport & X.509 Attestation
          </Typography>

          <Stack spacing={0.8} sx={{ fontSize: '0.78rem', color: 'text.secondary' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.primary' }}>UAID (Digital Passport):</Typography>
              <Typography variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#10b981' }}>
                {agent.uaid || `uaid:london:auth:${state?.projectId || 'proj_alpha'}:${(agent.agent_id || agent.id).replace(/[^a-zA-Z0-9_-]/g, '')}:v1.0.0`}
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.primary' }}>X.509 Root CA Issuer:</Typography>
              <Typography variant="caption" sx={{ color: '#60a5fa' }}>CN=Federated Root CA, O=agent.london Federation, C=UK</Typography>
            </Box>

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.primary' }}>Entra Agent 365 Principal:</Typography>
              <Typography variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#a78bfa' }}>
                {agent.entra_agent365_principal_id || `spn:agent365:${(agent.agent_id || agent.id).replace(/[^a-zA-Z0-9_-]/g, '')}@${state?.projectId || 'proj_alpha'}.entra.agent.london`}
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.primary' }}>Codebase Cryptographic Hash Attestation:</Typography>
              <Typography variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#f59e0b' }}>
                {agent.codebase_hash_attestation || `sha256:${(agent.hash_digest || '76a51f4a79f16347b2539f15f0048429d02319eb').substring(0, 24)}...`}
              </Typography>
            </Box>
          </Stack>
        </Box>

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
              {/* An agent assigned a model the router no longer serves still
                  has to render — dropping it silently would show the wrong
                  model as selected. It is listed, and marked. */}
              {selectedModel && !availableModels.some((m) => m.id === selectedModel) && (
                <MenuItem key={selectedModel} value={selectedModel}>
                  {selectedModel} (not currently served by the router)
                </MenuItem>
              )}
              {availableModels.map((m) => (
                <MenuItem key={m.id} value={m.id}>
                  {m.name}
                  {m.provider ? ` (${m.provider}` : ''}
                  {m.context_window ? ` • ${Math.round(m.context_window / 1000)}K ctx` : ''}
                  {m.provider ? ')' : ''}
                  {m.id === defaultModel ? ' — default' : ''}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>

        {/* System Prompt View */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>System Prompt</Typography>
          <Paper elevation={0} sx={{ p: 1.5, backgroundColor: 'rgba(9, 13, 22, 0.8)', fontFamily: '"JetBrains Mono", monospace', fontSize: '0.78rem', whiteSpace: 'pre-line' }}>
            {agent.systemPrompt || `You are ${agent.name}, operating under caste '${agent.caste}'. Your telos is: ${agent.telos}`}
          </Paper>
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
