import React, { useState, useEffect } from 'react';
import { api, attempt } from '../utils/api';
import { casteColor } from '../utils/caste';
import { FALLBACK_DEFAULT_MODEL } from '../utils/models';
import { Box, Typography, Button, Chip, Tabs, Tab, Tooltip, Alert, Paper,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, IconButton } from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import AddIcon from '@mui/icons-material/Add';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import MemoryIcon from '@mui/icons-material/Memory';
import AgentDetailModal from './AgentDetailModal';

export default function AgentRegistryView({ state, onOpenMaterialize, reloadToken = 0 }) {
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [agentModels, setAgentModels] = useState({});
  const [casteFilter, setCasteFilter] = useState('all');
  const [agents, setAgents] = useState([]);

  const [loadError, setLoadError] = useState(null);
  const [combos, setCombos] = useState([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data } = await attempt(
        api.get(`/api/projects/${state.projectId}/catalogued-combinations`));
      if (!cancelled && data) setCombos(data.combinations || []);
    })();
    return () => { cancelled = true; };
  }, [state.projectId, state.orgId, reloadToken]);

  const deleteCombo = async (agentId) => {
    if (!window.confirm('Remove this catalogued combination from the list?')) return;
    await attempt(api.del(
      `/api/projects/${state.projectId}/catalogued-combinations/${agentId}?org_id=${encodeURIComponent(state.orgId || 'org_default')}`));
    setCombos((prev) => prev.filter((c) => c.agent_id !== agentId));
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data, error } = await attempt(
        api.get(`/api/projects/${state.projectId}/agents`));
      if (cancelled) return;
      if (error) {
        // An empty registry and an unreachable one are different answers
        // (F.38), so the list is not silently left as it was.
        setLoadError(error);
        setAgents([]);
        return;
      }
      setLoadError(null);
      setAgents((data.agents || []).map((a) => ({
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
        // What makes an agent reproducible, and what a pipeline pins (F.21).
        version: a.version || null,
        content_hash: a.content_hash || null,
        version_status: a.version_status || null,
        lifecycle: a.lifecycle || 'active',
        slug: a.slug || null,
      })));
    })();
    return () => { cancelled = true; };
  }, [state.projectId, state.orgId, reloadToken]);

  const filteredAgents = agents.filter(a => casteFilter === 'all' || a.caste === casteFilter);

  const handleSaveModel = (agentId, modelId, newDescription) => {
    setAgentModels(prev => ({ ...prev, [agentId]: { modelId, description: newDescription } }));
  };

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      {/* The list either loaded or it did not. This error was captured and
          never rendered, so an unreachable registry looked like an empty
          civilisation (F.38). */}
      {loadError && (
        <Alert severity="error" sx={{ mb: 1 }}>{loadError.userMessage}</Alert>
      )}
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

      {/* Catalogued combinations: proven multi-agent runs kept as single,
          reusable agents. A pipeline of agents is a pipeline of one. */}
      {combos.length > 0 && (
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, color: '#a78bfa', mb: 1 }}>
            Catalogued combinations ({combos.length})
          </Typography>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead sx={{ backgroundColor: 'rgba(9, 13, 22, 0.8)' }}>
                <TableRow>
                  <TableCell sx={{ fontWeight: 700 }}>Name</TableCell>
                  <TableCell sx={{ fontWeight: 700 }}>Goal</TableCell>
                  <TableCell sx={{ fontWeight: 700 }} align="right">Agents</TableCell>
                  <TableCell sx={{ fontWeight: 700 }}>Handle</TableCell>
                  <TableCell sx={{ fontWeight: 700 }} align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {combos.map((c) => (
                  <TableRow key={c.agent_id} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{c.name}</TableCell>
                    <TableCell sx={{ color: 'text.secondary', maxWidth: 340,
                                     whiteSpace: 'nowrap', overflow: 'hidden',
                                     textOverflow: 'ellipsis' }}>
                      <Tooltip title={c.goal || ''}><span>{c.goal}</span></Tooltip>
                    </TableCell>
                    <TableCell align="right">{c.stage_count}</TableCell>
                    <TableCell sx={{ fontFamily: '"JetBrains Mono", monospace',
                                     fontSize: '0.75rem', color: '#93c5fd' }}>
                      {c.mcp_tool || '—'}
                      {c.mcp_tool && (
                        <Tooltip title="Copy the handle this combination is invoked by">
                          <IconButton size="small"
                                      onClick={() => navigator.clipboard?.writeText(c.mcp_tool)}>
                            <ContentCopyIcon sx={{ fontSize: 13 }} />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Remove from the list">
                        <IconButton size="small" onClick={() => deleteCombo(c.agent_id)}
                                    sx={{ color: '#f87171' }}>
                          <DeleteOutlineIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

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

      {/* Agents table: one row per agent — a ledger reads as a ledger. Click a
          row for the dossier (model assignment, keys, full telos). */}
      <TableContainer component={Paper}>
        <Table size="small" sx={{ minWidth: 720 }}>
          <TableHead sx={{ backgroundColor: 'rgba(9, 13, 22, 0.8)' }}>
            <TableRow>
              <TableCell sx={{ fontWeight: 700 }}>Agent</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Caste</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Cognition</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Model</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Version</TableCell>
              <TableCell sx={{ fontWeight: 700 }} align="right">Tokens</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredAgents.map((a) => {
              const config = agentModels[a.agent_id] || {};
              const assignedModel = config.modelId || FALLBACK_DEFAULT_MODEL;
              const llmDesc = config.description || a.telos;
              return (
                <TableRow key={a.agent_id} hover sx={{ cursor: 'pointer' }}
                          onClick={() => setSelectedAgent({ ...a, assignedModel, llmDescription: llmDesc })}>
                  <TableCell>
                    <Tooltip title={llmDesc || ''}>
                      <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                        <VerifiedUserIcon sx={{ fontSize: 14, color: '#10b981' }} />
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{a.name}</Typography>
                      </Box>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Chip label={(a.caste || '').toUpperCase()} size="small"
                          color={casteColor(a.caste)}
                          sx={{ height: 18, fontSize: '0.6rem', fontWeight: 700 }} />
                  </TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontSize: '0.8rem' }}>
                    {a.cog_func}{a.topo ? ` · ${a.topo}` : ''}
                  </TableCell>
                  <TableCell sx={{ fontFamily: '"JetBrains Mono", monospace',
                                   fontSize: '0.75rem', color: '#60a5fa' }}>
                    <MemoryIcon sx={{ fontSize: 12, mr: 0.5, verticalAlign: 'middle' }} />
                    {assignedModel}
                  </TableCell>
                  <TableCell>
                    {/* The version is what a pipeline pins, and the content hash
                        proves the pinned definition has not moved (F.21). */}
                    {a.version ? (
                      <Tooltip title={a.content_hash ? `content hash ${a.content_hash}` : 'no content hash recorded'}>
                        <Typography variant="caption"
                                    sx={{ fontFamily: '"JetBrains Mono", monospace',
                                          fontWeight: 700, color: '#38bdf8' }}>
                          v{a.version}
                          {a.content_hash && (
                            <span style={{ color: '#94a3b8', fontWeight: 400 }}>
                              {' '}· {String(a.content_hash).slice(0, 10)}
                            </span>
                          )}
                        </Typography>
                      </Tooltip>
                    ) : (
                      <Tooltip title="Exists in the graph but has no published version, so it cannot be pinned.">
                        <Typography variant="caption" sx={{ color: '#f59e0b', fontWeight: 700 }}>
                          unpublished
                        </Typography>
                      </Tooltip>
                    )}
                    {a.version_status && a.version_status !== 'active' && (
                      <Typography variant="caption" sx={{ color: '#f59e0b', display: 'block' }}>
                        {a.version_status}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="right" sx={{ color: '#10b981', fontWeight: 700,
                                                 fontSize: '0.8rem' }}>
                    {a.tokens != null ? `${a.tokens} CR` : '—'}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

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
