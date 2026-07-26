import React, { useState } from 'react';
import { Box, Paper, Tabs, Tab, Button, Chip, Typography, Stack, Dialog, DialogTitle, DialogContent, DialogActions, TextField } from '@mui/material';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import AddIcon from '@mui/icons-material/Add';
import HubIcon from '@mui/icons-material/Hub';
import PublicIcon from '@mui/icons-material/Public';

export default function ProjectTabsBar({ state, setState }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  const projects = state.projects || [
    { id: 'proj_alpha_civilization', name: 'Alpha Civilization Universe', agentsCount: 8, status: 'ACTIVE' },
    { id: 'proj_quantum_agents', name: 'Quantum Swarm Universe', agentsCount: 12, status: 'ACTIVE' },
    { id: 'proj_neural_synth', name: 'Neural Synthesis Universe', agentsCount: 5, status: 'ACTIVE' }
  ];

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
      agentsCount: 8,
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
        justify: 'space-between',
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

      {/* New Project Universe Button */}
      <Button
        variant="outlined"
        color="primary"
        size="small"
        startIcon={<AddIcon />}
        onClick={() => setCreateOpen(true)}
        sx={{ fontWeight: 700, fontSize: '0.78rem', textTransform: 'none' }}
      >
        Create Project Universe
      </Button>

      {/* Create Project Modal */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>
          🚀 Create New Project Universe
        </DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Instantiates a dedicated project realm in <strong>post-graph</strong> with auto-provisioned Prime Caste agents.
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
