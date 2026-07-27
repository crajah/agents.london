import React, { useState, useEffect } from 'react';
import {
  Box, Paper, Tabs, Tab, Button, Chip, Typography, Stack, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Alert, IconButton, Tooltip
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import PublicIcon from '@mui/icons-material/Public';
import KeyIcon from '@mui/icons-material/Key';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckIcon from '@mui/icons-material/Check';

export default function ProjectTabsBar({ state, setState }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [keyModalOpen, setKeyModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [copied, setCopied] = useState(false);
  const [projectApiKey, setProjectApiKey] = useState('A1B2-C3D4-E5F6-G7H8');

  const projects = state.projects || [
    { id: 'proj_alpha_civilization', name: 'Alpha Civilization Universe', agentsCount: 28, status: 'ACTIVE' },
    { id: 'proj_quantum_agents', name: 'Quantum Swarm Universe', agentsCount: 28, status: 'ACTIVE' },
    { id: 'proj_neural_synth', name: 'Neural Synthesis Universe', agentsCount: 28, status: 'ACTIVE' }
  ];

  useEffect(() => {
    // Fetch 16-character project API key for active project
    async function fetchApiKey() {
      try {
        const res = await fetch(`/api/projects/${state.projectId}/key`);
        if (res.ok) {
          const data = await res.json();
          if (data.api_key) setProjectApiKey(data.api_key);
        }
      } catch (e) {
        console.log('Using default project API key:', e);
      }
    }
    fetchApiKey();
  }, [state.projectId]);

  const handleTabChange = (event, newValue) => {
    if (newValue === '__create__') {
      setCreateOpen(true);
      return;
    }
    setState(prev => ({ ...prev, projectId: newValue }));
  };

  const handleCreateProject = () => {
    if (!newProjectName.trim()) return;
    const cleanId = `proj_${newProjectName.toLowerCase().replace(/[^a-z0-9]/g, '_')}`;

    const newProjObj = {
      id: cleanId,
      name: newProjectName.trim(),
      agentsCount: 28,
      status: 'ACTIVE'
    };

    setState(prev => ({
      ...prev,
      projectId: cleanId,
      projects: [...(prev.projects || projects), newProjObj]
    }));

    setNewProjectName('');
    setCreateOpen(false);
  };

  const handleCopyKey = () => {
    navigator.clipboard.writeText(projectApiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRegenerateKey = async () => {
    try {
      const res = await fetch(`/api/projects/${state.projectId}/key/regenerate`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.api_key) setProjectApiKey(data.api_key);
      }
    } catch (e) {
      // Generate fallback local 16-char key
      const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
      let r = '';
      for (let i = 0; i < 16; i++) r += chars.charAt(Math.floor(Math.random() * chars.length));
      setProjectApiKey(`${r.substring(0, 4)}-${r.substring(4, 8)}-${r.substring(8, 12)}-${r.substring(12, 16)}`);
    }
  };

  return (
    <Paper
      elevation={0}
      sx={{
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        px: 3,
        py: 0.5,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 2,
        backdropFilter: 'blur(10px)'
      }}
    >
      {/* Project Universe Selector Tabs */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flex: 1, overflowX: 'auto' }}>
        <Typography variant="caption" sx={{ fontWeight: 800, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.8px', display: 'flex', alignItems: 'center', gap: 0.5, pr: 1 }}>
          <PublicIcon sx={{ fontSize: 16 }} /> Project Universes:
        </Typography>

        <Tabs
          value={state.projectId}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          sx={{
            minHeight: 42,
            '& .MuiTab-root': {
              minHeight: 42,
              fontWeight: 700,
              fontSize: '0.82rem',
              color: 'text.secondary',
              borderRadius: '8px 8px 0 0',
              px: 2,
              transition: 'all 0.2s ease',
              '&.Mui-selected': {
                color: '#60a5fa',
                backgroundColor: 'rgba(59, 130, 246, 0.12)'
              }
            },
            '& .MuiTabs-indicator': {
              backgroundColor: '#3b82f6',
              height: 3,
              borderRadius: '3px 3px 0 0'
            }
          }}
        >
          {projects.map((p) => (
            <Tab
              key={p.id}
              value={p.id}
              label={
                <Stack direction="row" spacing={1} alignItems="center">
                  <span>{p.name}</span>
                  <Chip label={`${p.agentsCount} Agents`} size="small" color={state.projectId === p.id ? "primary" : "default"} sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700 }} />
                </Stack>
              }
            />
          ))}
        </Tabs>
      </Box>

      {/* Action Buttons: Project API Key & Create Project */}
      <Stack direction="row" spacing={1.5} alignItems="center">
        <Button
          variant="outlined"
          color="secondary"
          size="small"
          startIcon={<KeyIcon />}
          onClick={() => setKeyModalOpen(true)}
          sx={{ fontWeight: 700, fontSize: '0.78rem', textTransform: 'none' }}
        >
          🔑 Project API Key (MCP / A2A)
        </Button>

        <Button
          variant="contained"
          color="primary"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
          sx={{ fontWeight: 700, fontSize: '0.78rem', textTransform: 'none' }}
        >
          Create Universe
        </Button>
      </Stack>

      {/* Project API Key Settings Modal */}
      <Dialog open={keyModalOpen} onClose={() => setKeyModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
          🔑 Project API Key & Protocol Settings
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Restricts external <strong>Model Context Protocol (MCP)</strong> and <strong>Agent-to-Agent (A2A)</strong> direct protocol calls to project <code>{state.projectId}</code>.
          </Typography>

          <Alert severity="info" sx={{ borderRadius: 2, fontSize: '0.82rem' }}>
            <strong>16-Character Project API Key Format:</strong> 16 uppercase alphanumeric digits separated by hyphens (<code>XXXX-XXXX-XXXX-XXXX</code>).
          </Alert>

          <Paper sx={{ p: 2, backgroundColor: 'rgba(9, 13, 22, 0.85)', borderRadius: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                PROJECT API KEY ({state.projectId})
              </Typography>
              <Typography variant="h6" sx={{ fontFamily: '"JetBrains Mono", monospace', fontWeight: 800, color: '#10b981', letterSpacing: '1px' }}>
                {projectApiKey}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1}>
              <Tooltip title={copied ? "Copied!" : "Copy Key"}>
                <IconButton onClick={handleCopyKey} color="primary" size="small">
                  {copied ? <CheckIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
                </IconButton>
              </Tooltip>

              <Tooltip title="Regenerate Key">
                <IconButton onClick={handleRegenerateKey} color="secondary" size="small">
                  <RefreshIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          </Paper>

          <Box sx={{ p: 2, backgroundColor: 'rgba(15, 23, 42, 0.6)', borderRadius: 2, fontSize: '0.78rem', fontFamily: '"JetBrains Mono", monospace' }}>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#60a5fa', display: 'block', mb: 1 }}>
              MCP & A2A AUTHENTICATION HEADERS:
            </Typography>
            <div style={{ color: '#e2e8f0' }}>Authorization: Bearer {projectApiKey}</div>
            <div style={{ color: '#e2e8f0' }}>X-Project-API-Key: {projectApiKey}</div>
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setKeyModalOpen(false)} variant="contained" color="primary">
            Close
          </Button>
        </DialogActions>
      </Dialog>

      {/* Create Project Modal */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>
          🚀 Create New Project Universe
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Instantiates a dedicated project realm in <strong>post-graph</strong> with auto-provisioned 28 Prime Caste agents.
          </Typography>

          <TextField
            label="Project Universe Name"
            size="small"
            fullWidth
            placeholder="e.g. Neural Swarm, Autonomous Finance"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setCreateOpen(false)} color="inherit">Cancel</Button>
          <Button onClick={handleCreateProject} variant="contained" color="primary">
            Instantiate Universe
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
