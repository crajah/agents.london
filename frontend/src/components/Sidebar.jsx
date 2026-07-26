import React from 'react';
import {
  Box, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, Typography, Divider, Link
} from '@mui/material';
import SportsEsportsIcon from '@mui/icons-material/SportsEsports';
import HubIcon from '@mui/icons-material/Hub';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import BuildIcon from '@mui/icons-material/Build';
import PsychologyIcon from '@mui/icons-material/Psychology';
import ShieldIcon from '@mui/icons-material/Shield';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

export default function Sidebar({ currentTab, setCurrentTab, metrics }) {
  const menuItems = [
    { id: 'playground', label: 'Civilization Playground', icon: <SportsEsportsIcon /> },
    { id: 'discovery', label: 'Discovery & Composability', icon: <AutoAwesomeIcon /> },
    { id: 'civilization', label: 'Civilization Graph', icon: <HubIcon /> },
    { id: 'agents', label: 'Agent Registry & Kagent', icon: <SmartToyIcon /> },
    { id: 'tools', label: 'MCP Tool Registry', icon: <BuildIcon /> },
    { id: 'sessions', label: 'Shared Memory (post-graph-rag)', icon: <PsychologyIcon /> },
    { id: 'guardrails', label: 'Constitutional Guardrails', icon: <ShieldIcon /> },
  ];

  return (
    <Box sx={{ width: 280, flexShrink: 0, p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Navigation List */}
      <Paper sx={{ p: 1 }}>
        <List disablePadding>
          {menuItems.map((item) => {
            const isSelected = currentTab === item.id;
            return (
              <ListItem disablePadding key={item.id} sx={{ mb: 0.5 }}>
                <ListItemButton
                  selected={isSelected}
                  onClick={() => setCurrentTab(item.id)}
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

      {/* Civilization Metrics Card */}
      <Paper sx={{ p: 2, mt: 'auto', background: 'linear-gradient(135deg, rgba(19, 27, 46, 0.9) 0%, rgba(30, 41, 59, 0.9) 100%)' }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: 'text.primary', mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
          ⚡ Civilization Metrics
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: '0.8rem' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Active Scale:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#3b82f6' }}>1,000,000,000</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Permanent Agents:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#10b981' }}>8</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Materialized Progeny:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#a78bfa' }}>14</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">MCP Tools Linked:</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700, color: '#f59e0b' }}>8</Typography>
          </Box>
        </Box>

        <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,0.08)' }} />

        <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', fontSize: '0.7rem' }}>
          Brainchild of <Link href="https://www.linkedin.com/in/crajah/" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa', fontWeight: 600 }}>Chandan Rajah</Link> | <Link href="https://github.com/crajah" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa' }}>GitHub</Link>
        </Typography>
      </Paper>
    </Box>
  );
}
