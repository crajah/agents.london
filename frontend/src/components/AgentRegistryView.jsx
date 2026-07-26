import React, { useState } from 'react';
import { Box, Typography, Button, Grid, Card, CardContent, Chip, Stack } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import MemoryIcon from '@mui/icons-material/Memory';
import AgentDetailModal from './AgentDetailModal';

export default function AgentRegistryView({ state, onOpenMaterialize }) {
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [agentModels, setAgentModels] = useState({});

  const primeAgents = [
    { agent_id: `genesis-${state.projectId}`, name: `GenesisNode-${state.projectId}`, caste: 'genesis', telos: 'Root authority initializing civilizational infrastructure.', pubkey: 'ed25519:genesis_root_99a', tokens: 5000, rep: 100 },
    { agent_id: `archivist-${state.projectId}`, name: `OntologicalRegistry-${state.projectId}`, caste: 'archivist', telos: 'Universal agent ledger & cryptographic identity tracking.', pubkey: 'ed25519:archivist_ledger_42b', tokens: 3000, rep: 100 },
    { agent_id: `arbiter-${state.projectId}`, name: `ResourceArbiter-${state.projectId}`, caste: 'economist', telos: 'Utility token bank & compute credit allocations.', pubkey: 'ed25519:arbiter_bank_77c', tokens: 10000, rep: 100 },
    { agent_id: `judicature-${state.projectId}`, name: `JudicatureNode-${state.projectId}`, caste: 'judicature', telos: 'Constitutional law enforcement & dispute resolution.', pubkey: 'ed25519:judicature_law_88d', tokens: 4000, rep: 100 },
    { agent_id: `creator-${state.projectId}`, name: `AgentCreator-${state.projectId}`, caste: 'architect', telos: 'Materializes custom worker agents via Kagent.', pubkey: 'ed25519:creator_builder_11e', tokens: 2000, rep: 98 },
    { agent_id: `inspector-${state.projectId}`, name: `InspectorAgent-${state.projectId}`, caste: 'auditor', telos: 'Audits worker outputs & verifies signature compliance.', pubkey: 'ed25519:inspector_audit_33f', tokens: 1500, rep: 100 },
    { agent_id: `conductor-${state.projectId}`, name: `ConductorAgent-${state.projectId}`, caste: 'architect', telos: 'Queries Agent RAG source to orchestrate collaborators.', pubkey: 'ed25519:conductor_rag_55g', tokens: 2500, rep: 95 },
    { agent_id: `react-${state.projectId}`, name: `ReActAgent-${state.projectId}`, caste: 'task_workforce', telos: 'Executes Thought -> Action -> Observation reasoning loops.', pubkey: 'ed25519:react_loop_66h', tokens: 1200, rep: 92 }
  ];

  const getCasteColor = (caste) => {
    switch (caste) {
      case 'genesis': return 'secondary';
      case 'archivist': return 'info';
      case 'economist': return 'warning';
      case 'judicature': return 'error';
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
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Versioned Agent Registry & Progeny Lineage
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Click on any agent card to inspect details, assign underlying LLM models, and synthesize empirical I/O descriptions.
          </Typography>
        </Box>

        <Button variant="contained" color="primary" startIcon={<AddIcon />} onClick={onOpenMaterialize}>
          Materialize Worker Agent
        </Button>
      </Box>

      {/* Agents Grid */}
      <Grid container spacing={2.5}>
        {primeAgents.map((a) => {
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

                  <Typography variant="h6" sx={{ fontSize: '1.05rem', fontWeight: 700 }}>
                    {a.name}
                  </Typography>

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
