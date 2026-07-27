import React from 'react';
import {
  AppBar, Toolbar, Typography, Box, Select, MenuItem, FormControl, InputLabel, Button, Chip, Link, IconButton
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import LockIcon from '@mui/icons-material/Lock';
import AddIcon from '@mui/icons-material/Add';
import KeyIcon from '@mui/icons-material/Key';
import LogoutIcon from '@mui/icons-material/Logout';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';

export default function Header({
  state, setState, userSession, onLogout, onOpenSSO, onOpenMaterialize, onOpenBYOM, onToggleMobileSidebar
}) {
  return (
    <AppBar position="static" color="transparent" elevation={0} sx={{ borderBottom: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(12px)', backgroundColor: 'rgba(11, 15, 25, 0.85)', px: { xs: 1, sm: 2 } }}>
      <Toolbar sx={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 1.5, py: 1 }}>
        {/* Mobile Hamburger Menu Button & Brand */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <IconButton
            color="inherit"
            edge="start"
            onClick={onToggleMobileSidebar}
            sx={{ display: { lg: 'none' }, color: '#60a5fa' }}
          >
            <MenuIcon />
          </IconButton>

          <Box sx={{ fontSize: '1.8rem', lineHeight: 1 }}>🏛️</Box>
          <Box>
            <Typography variant="h6" sx={{
              fontWeight: 800,
              background: 'linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              letterSpacing: '-0.5px'
            }}>
              agent.london
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Chip label="1B Agent Civilization" size="small" color="primary" variant="outlined" sx={{ height: 18, fontSize: '0.65rem' }} />
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.7rem', display: { xs: 'none', sm: 'inline' } }}>
                Brainchild of <Link href="https://www.linkedin.com/in/crajah/" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa', fontWeight: 600 }}>Chandan Rajah</Link>
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* Tenancy Selector Bar */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ minWidth: { xs: 120, sm: 160 } }}>
            <InputLabel sx={{ fontSize: '0.75rem' }}>Organization</InputLabel>
            <Select
              value={state.orgId}
              label="Organization"
              onChange={(e) => setState(prev => ({ ...prev, orgId: e.target.value }))}
              sx={{ fontSize: '0.85rem' }}
            >
              <MenuItem value="org_london_meta">org_london_meta</MenuItem>
              <MenuItem value="org_deepmind_ai">org_deepmind_ai</MenuItem>
              <MenuItem value="org_global_corp">org_global_corp</MenuItem>
              {state.orgId.startsWith('org_user_') && (
                <MenuItem value={state.orgId}>{state.orgId} (Synthetic Org)</MenuItem>
              )}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: { xs: 120, sm: 160 } }}>
            <InputLabel sx={{ fontSize: '0.75rem' }}>User Identity</InputLabel>
            <Select
              value={state.userId}
              label="User Identity"
              onChange={(e) => setState(prev => ({ ...prev, userId: e.target.value }))}
              sx={{ fontSize: '0.85rem' }}
            >
              <MenuItem value="user_chandan">chandan@agent.london</MenuItem>
              <MenuItem value="user_alice">alice@agent.london</MenuItem>
              {state.userId.startsWith('user_') && (
                <MenuItem value={state.userId}>{state.userId}</MenuItem>
              )}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: { xs: 130, sm: 170 } }}>
            <InputLabel sx={{ fontSize: '0.75rem' }}>Project Universe</InputLabel>
            <Select
              value={state.projectId}
              label="Project Universe"
              onChange={(e) => setState(prev => ({ ...prev, projectId: e.target.value }))}
              sx={{ fontSize: '0.85rem' }}
            >
              <MenuItem value="proj_alpha_civilization">proj_alpha_civilization</MenuItem>
              <MenuItem value="proj_quantum_agents">proj_quantum_agents</MenuItem>
            </Select>
          </FormControl>

          <Button variant="outlined" color="info" startIcon={<KeyIcon />} onClick={onOpenBYOM} size="small" sx={{ fontSize: '0.75rem' }}>
            BYOM / BYOK
          </Button>

          {userSession ? (
            <Chip
              label={userSession.email}
              color="success"
              onDelete={onLogout}
              deleteIcon={<LogoutIcon />}
              sx={{ fontWeight: 600, fontSize: '0.8rem' }}
            />
          ) : (
            <Button variant="outlined" color="primary" startIcon={<LockIcon />} onClick={onOpenSSO} size="small" sx={{ fontSize: '0.75rem' }}>
              Sign In
            </Button>
          )}

          <Button variant="contained" color="secondary" startIcon={<AddIcon />} onClick={onOpenMaterialize} size="small" sx={{ fontWeight: 700, fontSize: '0.75rem' }}>
            Materialize Agent
          </Button>
        </Box>

        {/* Connection Badge */}
        <Box sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center', gap: 0.8 }}>
          <FiberManualRecordIcon sx={{ fontSize: 12, color: state.wsConnected ? '#10b981' : '#f59e0b' }} />
          <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 500 }}>
            {state.wsConnected ? 'Redis Bus Active' : 'Local Stream Mode'}
          </Typography>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
