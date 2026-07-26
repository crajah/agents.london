import React, { useState } from 'react';
import { Box, Typography, Button, Grid, Card, CardContent, Chip, Stack, Tabs, Tab } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import MemoryIcon from '@mui/icons-material/Memory';
import AgentDetailModal from './AgentDetailModal';

export default function AgentRegistryView({ state, onOpenMaterialize }) {
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [agentModels, setAgentModels] = useState({});
  const [casteFilter, setCasteFilter] = useState('all');

  const prime28Agents = [
    // Genesis Nodes (6)
    { agent_id: `prime-orchestrator-${state.projectId}`, name: `The Prime Orchestrator`, caste: 'genesis', cog_func: 'Governance', topo: 'Orchestrate', telos: 'Manages the overarching flow of the civilization goals.', pubkey: 'ed25519:prime_orch_99a', tokens: 5000, rep: 100 },
    { agent_id: `high-arbiter-${state.projectId}`, name: `The High Arbiter`, caste: 'genesis', cog_func: 'Governance', topo: 'Hierarchy', telos: 'The ultimate authority in dispute resolution and constitutional interpretation.', pubkey: 'ed25519:high_arb_88b', tokens: 4500, rep: 100 },
    { agent_id: `protocol-architect-${state.projectId}`, name: `The Protocol Architect`, caste: 'genesis', cog_func: 'Governance', topo: 'Chain', telos: 'Designs the sequential rules of interaction between all other agents.', pubkey: 'ed25519:proto_arch_77c', tokens: 4000, rep: 100 },
    { agent_id: `boundary-warden-${state.projectId}`, name: `The Boundary Warden`, caste: 'genesis', cog_func: 'Governance', topo: 'Route', telos: 'Regulates interactions with external systems and the outside world.', pubkey: 'ed25519:bound_ward_66d', tokens: 3500, rep: 99 },
    { agent_id: `resource-sovereign-${state.projectId}`, name: `The Resource Sovereign`, caste: 'genesis', cog_func: 'Governance', topo: 'Parallel', telos: 'Oversees macro-level resource allocation across the civilization.', pubkey: 'ed25519:res_sov_55e', tokens: 10000, rep: 100 },
    { agent_id: `evolution-driver-${state.projectId}`, name: `The Evolution Driver`, caste: 'genesis', cog_func: 'Governance', topo: 'Loop', telos: 'Governs the iterative improvement of the civilization core protocols.', pubkey: 'ed25519:evo_drv_44f', tokens: 3000, rep: 98 },

    // Ontological Registry (8)
    { agent_id: `grand-ledger-${state.projectId}`, name: `The Grand Ledger`, caste: 'archivist', cog_func: 'Memory', topo: 'Hierarchy', telos: 'Maintains the foundational database of all agent identities and lineages.', pubkey: 'ed25519:grand_ldg_33g', tokens: 3000, rep: 100 },
    { agent_id: `pattern-seer-${state.projectId}`, name: `The Pattern Seer`, caste: 'archivist', cog_func: 'Perception', topo: 'Orchestrate', telos: 'Analyzes macro-trends and emergent behaviors across the billion-agent population.', pubkey: 'ed25519:pat_seer_22h', tokens: 2500, rep: 97 },
    { agent_id: `state-chronicler-${state.projectId}`, name: `The State Chronicler`, caste: 'archivist', cog_func: 'Memory', topo: 'Chain', telos: 'Records the sequential history and major events of the civilization.', pubkey: 'ed25519:state_chr_11i', tokens: 2200, rep: 98 },
    { agent_id: `sensorium-prime-${state.projectId}`, name: `The Sensorium Prime`, caste: 'archivist', cog_func: 'Perception', topo: 'Parallel', telos: 'Processes vast streams of raw environmental and systemic data.', pubkey: 'ed25519:sens_prm_00j', tokens: 2800, rep: 96 },
    { agent_id: `context-weaver-${state.projectId}`, name: `The Context Weaver`, caste: 'archivist', cog_func: 'Memory', topo: 'Route', telos: 'Directs specialized memory access based on contextual queries.', pubkey: 'ed25519:ctx_wvr_99k', tokens: 2400, rep: 97 },
    { agent_id: `anomaly-detector-${state.projectId}`, name: `The Anomaly Detector`, caste: 'archivist', cog_func: 'Perception', topo: 'Loop', telos: 'Continuously scans for systemic irregularities or deviations.', pubkey: 'ed25519:anom_det_88l', tokens: 2600, rep: 99 },
    { agent_id: `archive-cycler-${state.projectId}`, name: `The Archive Cycler`, caste: 'archivist', cog_func: 'Memory', topo: 'Loop', telos: 'Manages data retention, compression, and archival pruning.', pubkey: 'ed25519:arch_cyc_77m', tokens: 2100, rep: 95 },
    { agent_id: `signal-router-${state.projectId}`, name: `The Signal Router`, caste: 'archivist', cog_func: 'Perception', topo: 'Route', telos: 'Directs incoming data streams to the appropriate processing nodes.', pubkey: 'ed25519:sig_rtr_66n', tokens: 2300, rep: 96 },

    // Logic Engines (8)
    { agent_id: `master-strategist-${state.projectId}`, name: `The Master Strategist`, caste: 'architect', cog_func: 'Reasoning', topo: 'Hierarchy', telos: 'Formulates long-term plans and decomposes massive problems.', pubkey: 'ed25519:mst_str_55o', tokens: 3200, rep: 99 },
    { agent_id: `prime-executor-${state.projectId}`, name: `The Prime Executor`, caste: 'architect', cog_func: 'Action', topo: 'Orchestrate', telos: 'Translates high-level strategies into actionable commands.', pubkey: 'ed25519:prm_exe_44p', tokens: 3500, rep: 98 },
    { agent_id: `inference-chain-${state.projectId}`, name: `The Inference Chain`, caste: 'architect', cog_func: 'Reasoning', topo: 'Chain', telos: 'Handles deep, sequential logical deductions.', pubkey: 'ed25519:inf_chn_33q', tokens: 2900, rep: 97 },
    { agent_id: `action-sequencer-${state.projectId}`, name: `The Action Sequencer`, caste: 'architect', cog_func: 'Action', topo: 'Chain', telos: 'Ensures complex multi-step actions are executed in precise required order.', pubkey: 'ed25519:act_seq_22r', tokens: 2700, rep: 96 },
    { agent_id: `polymath-node-${state.projectId}`, name: `The Polymath Node`, caste: 'architect', cog_func: 'Reasoning', topo: 'Parallel', telos: 'Evaluates multiple hypothetical scenarios concurrently.', pubkey: 'ed25519:poly_nd_11s', tokens: 3100, rep: 98 },
    { agent_id: `swarm-commander-${state.projectId}`, name: `The Swarm Commander`, caste: 'architect', cog_func: 'Action', topo: 'Parallel', telos: 'Directs massive numbers of temporary worker agents in tasks.', pubkey: 'ed25519:swm_cmd_00t', tokens: 5000, rep: 99 },
    { agent_id: `decision-router-${state.projectId}`, name: `The Decision Router`, caste: 'architect', cog_func: 'Reasoning', topo: 'Route', telos: 'Classifies problems and routes them to specialized reasoning engines.', pubkey: 'ed25519:dec_rtr_99u', tokens: 2800, rep: 97 },
    { agent_id: `tool-master-${state.projectId}`, name: `The Tool Master`, caste: 'architect', cog_func: 'Action', topo: 'Route', telos: 'Maintains registry of all available external tools and APIs.', pubkey: 'ed25519:tool_mst_88v', tokens: 3300, rep: 98 },

    // Evaluators (6)
    { agent_id: `grand-critic-${state.projectId}`, name: `The Grand Critic`, caste: 'auditor', cog_func: 'Reflection', topo: 'Hierarchy', telos: 'Establishes ultimate standards for success and quality across all tasks.', pubkey: 'ed25519:grd_crt_77w', tokens: 2400, rep: 100 },
    { agent_id: `nexus-coordinator-${state.projectId}`, name: `The Nexus Coordinator`, caste: 'auditor', cog_func: 'Collaboration', topo: 'Orchestrate', telos: 'Manages formation and dissolution of complex agent alliances (guilds).', pubkey: 'ed25519:nex_crd_66x', tokens: 2600, rep: 97 },
    { agent_id: `feedback-loop-${state.projectId}`, name: `The Feedback Loop`, caste: 'auditor', cog_func: 'Reflection', topo: 'Loop', telos: 'Continuously analyzes outcomes against predictions to improve performance.', pubkey: 'ed25519:fbk_lop_55y', tokens: 2200, rep: 98 },
    { agent_id: `protocol-translator-${state.projectId}`, name: `The Protocol Translator`, caste: 'auditor', cog_func: 'Collaboration', topo: 'Route', telos: 'Ensures disparate agent factions or sub-systems communicate seamlessly.', pubkey: 'ed25519:prt_trn_44z', tokens: 2100, rep: 96 },
    { agent_id: `self-corrector-${state.projectId}`, name: `The Self Corrector`, caste: 'auditor', cog_func: 'Reflection', topo: 'Chain', telos: 'Analyzes specific failures and dictates immediate sequential steps for recovery.', pubkey: 'ed25519:slf_crt_331', tokens: 2500, rep: 99 },
    { agent_id: `synchronicity-engine-${state.projectId}`, name: `The Synchronicity Engine`, caste: 'auditor', cog_func: 'Collaboration', topo: 'Parallel', telos: 'Ensures parallel workstreams remain aligned toward shared goal.', pubkey: 'ed25519:syn_eng_222', tokens: 2900, rep: 98 }
  ];

  const filteredAgents = prime28Agents.filter(a => casteFilter === 'all' || a.caste === casteFilter);

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
            The 28 Permanent Prime Agents Scaffolding Ledger
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
        <Tab value="all" label="All 28 Prime Scaffolding" />
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
