import React, { useState, useEffect } from 'react';
import { Box, Typography, Button, Grid, Card, CardContent, Chip, Stack, Tabs, Tab } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import MemoryIcon from '@mui/icons-material/Memory';
import AgentDetailModal from './AgentDetailModal';

export default function AgentRegistryView({ state, onOpenMaterialize }) {
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [agentModels, setAgentModels] = useState({});
  const [casteFilter, setCasteFilter] = useState('all');
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const res = await fetch(`/api/projects/${state.projectId}/agents?org_id=${state.orgId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.agents && data.agents.length > 0) {
            setAgents(data.agents.map(a => ({
              agent_id: a.agent_id || a.id,
              name: a.name,
              caste: a.caste,
              cog_func: a.cog_func,
              topo: a.topo,
              telos: a.telos,
              pubkey: a.pubkey,
              tokens: a.tokens,
              rep: a.rep,
              assignedModel: a.assignedModel,
              is_prime: a.is_prime,
            })));
          }
        }
      } catch (e) {
        console.error('Error fetching agents:', e);
      }
    }
    fetchAgents();
  }, [state.projectId, state.orgId]);

  const filteredAgents = agents.filter(a => casteFilter === 'all' || a.caste === casteFilter);

  const getCasteColor = (caste) => {
    switch (caste) {
      case 'genesis': return 'secondary';
      case 'archivist': return 'info';
      case 'architect': return 'primary';
      case 'auditor': return 'success';
      default: return 'default';
    }
  };

  const handleSaveModel = (agentId, modelId, newDescription) => {
    setAgentModels(prev => ({ ...prev, [agentId]: { modelId, description: newDescription } }));
  };

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Prime Agents Scaffolding Ledger
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Universal agent ledger tracking existence, caste, cognitive function, execution topology, and public keys.
          </Typography>
        </Box>

        <Button variant="contained" color="primary" startIcon={<AddIcon />} onClick={onOpenMaterialize}>
          Materialize Worker Agent
        </Button>
      </Box>

      {/* Caste Filter Tabs */}
      <Tabs
        value={casteFilter}
        onChange={(e, val) => setCasteFilter(val)}
        sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}
      >
        <Tab value="all" label="All Prime Agents" />
        <Tab value="genesis" label="Genesis Nodes (6)" />
        <Tab value="archivist" label="Ontological Registry (8)" />
        <Tab value="architect" label="Logic Engines (8)" />
        <Tab value="auditor" label="Evaluators (6)" />
      </Tabs>

      {/* Agents Grid */}
      <Grid container spacing={2.5}>
        {filteredAgents.map((a) => {
          const config = agentModels[a.agent_id] || {};
          const assignedModel = config.modelId || 'MiniMax-M2.7';
          const llmDesc = config.description || a.telos;

          return (
            <Grid item xs={12} sm={6} md={4} lg={3} key={a.agent_id}>
              <Card
                onClick={() => setSelectedAgent({ ...a, assignedModel, llmDescription: llmDesc })}
                sx={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  cursor: 'pointer',
                  '&:hover': {
                    borderColor: '#3b82f6'
                  }
                }}
              >
                <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Chip label={a.caste.toUpperCase()} size="small" color={getCasteColor(a.caste)} sx={{ fontWeight: 700, fontSize: '0.65rem' }} />
                    <VerifiedUserIcon sx={{ fontSize: 16, color: '#10b981' }} />
                  </Stack>

                  <Typography variant="h6" sx={{ fontSize: '1.02rem', fontWeight: 700 }}>
                    {a.name}
                  </Typography>

                  <Stack direction="row" spacing={0.8}>
                    <Chip label={a.cog_func} size="small" color="primary" sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700 }} />
                    <Chip label={a.topo} size="small" color="secondary" sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700 }} />
                  </Stack>

                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.82rem', flex: 1, lineHeight: 1.5 }}>
                    {llmDesc}
                  </Typography>

                  <Chip
                    icon={<MemoryIcon sx={{ fontSize: 14 }} />}
                    label={assignedModel}
                    size="small"
                    color="primary"
                    variant="outlined"
                    sx={{ fontSize: '0.68rem', fontFamily: '"JetBrains Mono", monospace' }}
                  />

                  <Box sx={{ pt: 1, borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', flexDirection: 'column', gap: 0.5, fontSize: '0.75rem' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: '"JetBrains Mono", monospace' }}>
                      Key: {a.pubkey}
                    </Typography>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Typography variant="caption" color="text.secondary">Tokens:</Typography>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: '#10b981' }}>{a.tokens} CR</Typography>
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      {/* Detail Modal */}
      {selectedAgent && (
        <AgentDetailModal
          open={Boolean(selectedAgent)}
          onClose={() => setSelectedAgent(null)}
          agent={selectedAgent}
          onSaveModel={handleSaveModel}
          state={state}
        />
      )}
    </Box>
  );
}
