import React from 'react';
import {
  Box, Paper, Typography, Button, Stack, Container
} from '@mui/material';

import Logo from './Logo';

/**
 * Two doors, both through the platform authority (agents.london/authority),
 * both verified. The unverified email route is gone: an address anyone can
 * type is not an identity, and a lock screen that offers it invites exactly
 * the confusion it warns about. The authority redirects to the provider,
 * verifies the exchange server-side, and sends the person back here with a
 * short-lived RS256 token the backend checks against the authority's JWKS.
 */
const AUTHORITY_BASE = import.meta.env.VITE_AUTHORITY_BASE || '/authority';

export function authorityLoginUrl(provider) {
  const returnTo = `${window.location.pathname}${window.location.search}`;
  return `${AUTHORITY_BASE}/login/${provider}?return_to=${encodeURIComponent(returnTo || '/civilization/')}`;
}

export default function AuthLockScreen() {
  return (
    <Box sx={{
      height: '100vh',
      width: '100vw',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'background.default',
      backgroundImage: 'none'
    }}>
      <Container maxWidth="sm">
        <Paper
          elevation={0}
          sx={{
            p: 4,
            borderRadius: 4,
            backgroundColor: 'background.paper',
            backdropFilter: 'blur(20px)',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            gap: 3
          }}
        >
          {/* Header Icon & Brand */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5 }}>
            <Logo size={48} variant="auto" />
            <Typography variant="body2" color="text.secondary">
              Multi-Agent Civilization Platform
            </Typography>
          </Box>

          <Stack spacing={1.5}>
            <Button
              variant="contained"
              fullWidth
              size="large"
              href={authorityLoginUrl('google')}
              sx={{
                backgroundColor: '#ffffff',
                color: '#1f2937',
                '&:hover': { backgroundColor: '#f9fafb' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={<svg width="20" height="20" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>}
            >
              Sign in with Google
            </Button>

            <Button
              variant="contained"
              fullWidth
              size="large"
              href={authorityLoginUrl('microsoft')}
              sx={{
                backgroundColor: '#2f2f2f',
                color: '#ffffff',
                '&:hover': { backgroundColor: '#3f3f3f' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={<svg width="20" height="20" viewBox="0 0 23 23"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M12 1h10v10H12z"/><path fill="#05a6f0" d="M1 12h10v10H1z"/><path fill="#ffba08" d="M12 12h10v10H12z"/></svg>}
            >
              Sign in with Microsoft
            </Button>
          </Stack>

          <Typography variant="caption" color="text.secondary">
            Sign-in is verified by the platform authority. There is no
            unverified route in.
          </Typography>
        </Paper>
      </Container>
    </Box>
  );
}
