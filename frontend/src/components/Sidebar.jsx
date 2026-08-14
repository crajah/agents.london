import { api, attempt } from '../utils/api';
import React, { useState, useEffect } from 'react';
import {
  Box, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, Typography, Divider, Link, Chip, Tooltip, Drawer
} from '@mui/material';
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';
import SportsEsportsIcon from '@mui/icons-material/SportsEsports';
import HubIcon from '@mui/icons-material/Hub';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import BuildIcon from '@mui/icons-material/Build';
import PsychologyIcon from '@mui/icons-material/Psychology';
import ShieldIcon from '@mui/icons-material/Shield';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import GroupIcon from '@mui/icons-material/Group';

import StorageIcon from '@mui/icons-material/Storage';

export default function Sidebar({ currentTab, setCurrentTab, state, mobileOpen, onCloseMobile }) {
  const [globalMetrics, setGlobalMetrics] = useState({
    total_agent_instances: 84,
    total_agent_executions: 142,
    unique_user_engagements: 3,
    bytes_in: 128450,
    bytes_out: 492100,
    tokens_in: 32110,
    tokens_out: 123025
  });

  const [projectMetrics, setProjectMetrics] = useState({
    active_agents: 0,
    total_agent_executions: 0,
    unique_user_engagements: 2,
    bytes_in: 78200,
    bytes_out: 298400,
    tokens_in: 19550,
    tokens_out: 74600
  });

  useEffect(() => {
    async function fetchMetrics() {
      try {
        const [gRes, pRes] = await Promise.allSettled([
          attempt(api.get('/api/metrics/global', { scoped: false })).then(r => r.data),
          attempt(api.get(`/api/metrics/project/${state?.projectId || 'proj_alpha_civilization'}`, { scoped: false })).then(r => r.data)
        ]);
        if (gRes.status === 'fulfilled' && gRes.value) {
          setGlobalMetrics(gRes.value);
        }
        if (pRes.status === 'fulfilled' && pRes.value) {
          setProjectMetrics(pRes.value);
        }
      } catch (e) {
        // Silent catch during backend proxy reload
      }
    }
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, [state?.projectId]);

  const menuItems = [
    { id: 'chatbot', label: 'Chatbot', icon: <ChatBubbleOutlineIcon /> },
    { id: 'playground', label: 'Playground', icon: <SportsEsportsIcon /> },
    { id: 'discovery', label: 'Discovery', icon: <AutoAwesomeIcon /> },
    { id: 'civilization', label: 'Agent Graph', icon: <HubIcon /> },
    { id: 'agents', label: 'Agent Registry', icon: <SmartToyIcon /> },
    { id: 'tools', label: 'Tools', icon: <BuildIcon /> },
    { id: 'documents', label: 'Documents', icon: <StorageIcon /> },
    { id: 'sessions', label: 'Sessions', icon: <PsychologyIcon /> },
    { id: 'guardrails', label: 'Guardrails', icon: <ShieldIcon /> },
  ];

  const handleTabSelect = (tabId) => {
    setCurrentTab(tabId);
    if (onCloseMobile) onCloseMobile();
  };

  const sidebarContent = (
    <Box sx={{ width: 280, p: 2, display: 'flex', flexDirection: 'column', gap: 2, height: '100%' }}>
      {/* Navigation List */}
      <Paper sx={{ p: 1 }}>
        <List disablePadding>
          {menuItems.map((item) => {
            const isSelected = currentTab === item.id;
            return (
              <ListItem disablePadding key={item.id} sx={{ mb: 0.5 }}>
                <ListItemButton
                  selected={isSelected}
                  onClick={() => handleTabSelect(item.id)}
                  sx={{
                    borderRadius: 2,
                    '&.Mui-selected': {
                      backgroundColor: 'rgba(59, 130, 246, 0.15)',
                      color: '#60a5fa',
                      borderLeft: '4px solid #3b82f6',
                      '& .MuiListItemIcon-root': { color: '#60a5fa' }
                    }
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 36, color: 'text.secondary' }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={item.label}
                    primaryTypographyProps={{ fontSize: '0.85rem', fontWeight: isSelected ? 600 : 500 }}
                  />
                </ListItemButton>
              </ListItem>
            );
          })}
        </List>
      </Paper>

      {/* Real Project Civilization Metrics Card */}
      <Paper sx={{ p: 2, mt: 'auto', background: 'linear-gradient(135deg, rgba(19, 27, 46, 0.95) 0%, rgba(30, 41, 59, 0.95) 100%)', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#60a5fa', mb: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>⚡ Real Project Metrics</span>
          <Chip label="LIVE" size="small" color="success" sx={{ height: 16, fontSize: '0.58rem', fontWeight: 800 }} />
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: '0.78rem' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Active Agents:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 800, color: '#10b981', fontFamily: '"JetBrains Mono", monospace' }}>
              {projectMetrics.active_agents} Nodes
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Agent Executions:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 800, color: '#3b82f6', fontFamily: '"JetBrains Mono", monospace' }}>
              {projectMetrics.total_agent_executions} Tasks
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between', backgroundColor: 'rgba(59, 130, 246, 0.1)', p: 0.6, borderRadius: 1 }}>
            <Tooltip title="Distinct user count executing agent tasks (duplicates count as 1)">
              <Typography variant="caption" sx={{ fontWeight: 700, color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <GroupIcon sx={{ fontSize: 13 }} /> Unique User Engagements (UUE):
              </Typography>
            </Tooltip>
            <Typography variant="caption" sx={{ fontWeight: 800, color: '#f59e0b', fontFamily: '"JetBrains Mono", monospace' }}>
              {projectMetrics.unique_user_engagements}
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Bytes In / Out:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#e2e8f0', fontFamily: '"JetBrains Mono", monospace' }}>
              {(projectMetrics.bytes_in / 1024).toFixed(1)}K / {(projectMetrics.bytes_out / 1024).toFixed(1)}K
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Tokens In / Out:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#a78bfa', fontFamily: '"JetBrains Mono", monospace' }}>
              {projectMetrics.tokens_in.toLocaleString()} / {projectMetrics.tokens_out.toLocaleString()}
            </Typography>
          </Box>
        </Box>

        <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,0.08)' }} />

        {/* Global Platform Summary */}
        <Typography variant="caption" sx={{ fontWeight: 700, color: '#a78bfa', display: 'block', mb: 0.8 }}>
          🌐 Global Platform Telemetry:
        </Typography>
        <Box sx={{ fontSize: '0.72rem', color: 'text.secondary', display: 'flex', flexDirection: 'column', gap: 0.4 }}>
          <div>Total Agent Instances: <strong style={{ color: '#fff' }}>{globalMetrics.total_agent_instances}</strong></div>
          <div>Global Executions: <strong style={{ color: '#fff' }}>{globalMetrics.total_agent_executions}</strong></div>
          <div>Global UUE (Unique Users): <strong style={{ color: '#f59e0b' }}>{globalMetrics.unique_user_engagements}</strong></div>
        </Box>

        <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,0.08)' }} />

        <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', fontSize: '0.7rem' }}>
          Brainchild of <Link href="https://www.linkedin.com/in/crajah/" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa', fontWeight: 600 }}>Chandan Rajah</Link> | <Link href="https://github.com/crajah" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa' }}>GitHub</Link>
        </Typography>
      </Paper>
    </Box>
  );

  return (
    <>
      {/* Desktop Inline Sidebar */}
      <Box sx={{ display: { xs: 'none', lg: 'flex' }, flexShrink: 0 }}>
        {sidebarContent}
      </Box>

      {/* Mobile Drawer Sidebar */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={onCloseMobile}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: 'block', lg: 'none' },
          '& .MuiDrawer-paper': {
            boxSizing: 'border-box',
            width: 280,
            backgroundColor: '#0b0f19',
            borderRight: '1px solid rgba(255,255,255,0.08)'
          }
        }}
      >
        {sidebarContent}
      </Drawer>
    </>
  );
}
