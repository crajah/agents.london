import React, { useState } from 'react';
import {
  Box, Paper, Typography, Button, TextField, Stack, Container, Divider, Alert,
  CircularProgress
} from '@mui/material';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';

import { triggerGoogleOIDC, triggerMicrosoftOIDC } from '../utils/oidc';
import Logo from './Logo';

const GENERIC_EMAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
  "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
  "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
  "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
  "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
]);

export default function AuthLockScreen({ onAuthenticate }) {
  const [email, setEmail] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState(null);

  const resolveTenancy = (rawEmail) => {
    if (!rawEmail || !rawEmail.includes('@')) {
      return { userPart: 'user', domainPart: 'unknown', orgId: 'org_unknown', isGeneric: true, clean: rawEmail || '' };
    }
    const clean = rawEmail.toLowerCase().trim();
    const parts = clean.split('@');
    const userPart = (parts[0] || 'user').replace(/[^a-z0-9]/g, '_');
    const domainPart = parts[1] || 'gmail.com';
    const sanitizedDomain = domainPart.replace(/[^a-z0-9]/g, '_');

    const isGeneric = GENERIC_EMAIL_DOMAINS.has(domainPart);
    const orgId = isGeneric ? `org_user_${userPart}_${sanitizedDomain}` : `org_${sanitizedDomain}`;
    return { userPart, domainPart, orgId, isGeneric, clean };
  };

  const tenancy = resolveTenancy(email);

  const handleOAuthSuccess = (session) => {
    setAuthLoading(false);
    setAuthError(null);
    onAuthenticate(session);
  };

  const handleOAuthError = (errorMsg) => {
    setAuthLoading(false);
    setAuthError(errorMsg);
  };

  const handleEmailLogin = () => {
    if (!email || !email.includes('@')) return;
    const resolved = resolveTenancy(email);
    onAuthenticate({
      email: resolved.clean,
      orgId: resolved.orgId,
      userId: `user_${resolved.userPart}`,
      isGeneric: resolved.isGeneric,
    });
  };

  return (
    <Box sx={{
      height: '100vh',
      width: '100vw',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'background.default',
      backgroundImage: (theme) => theme.palette.mode === 'dark'
        ? 'radial-gradient(circle at 50% 30%, rgba(66, 133, 244, 0.1) 0%, transparent 60%)'
        : 'radial-gradient(circle at 50% 30%, rgba(26, 115, 232, 0.06) 0%, transparent 60%)'
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

          {/* Error Display */}
          {authError && (
            <Alert severity="error" onClose={() => setAuthError(null)} sx={{ borderRadius: 2, textAlign: 'left' }}>
              {authError}
            </Alert>
          )}

          {/* Google and Microsoft OIDC Authentication Buttons */}
          <Stack spacing={1.5}>
            <Button
              variant="contained"
              fullWidth
              size="large"
              disabled={authLoading}
              onClick={() => {
                setAuthLoading(true);
                setAuthError(null);
                triggerGoogleOIDC(handleOAuthSuccess, handleOAuthError);
              }}
              sx={{
                backgroundColor: '#ffffff',
                color: '#1f2937',
                '&:hover': { backgroundColor: '#f9fafb' },
                '&.Mui-disabled': { backgroundColor: 'rgba(255,255,255,0.3)' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={authLoading ? <CircularProgress size={20} color="inherit" /> : <svg width="20" height="20" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>}
            >
              Sign in with Google
            </Button>

            <Button
              variant="contained"
              fullWidth
              size="large"
              disabled={authLoading}
              onClick={() => {
                setAuthLoading(true);
                setAuthError(null);
                triggerMicrosoftOIDC(handleOAuthSuccess, handleOAuthError).catch(handleOAuthError);
              }}
              sx={{
                backgroundColor: '#2f2f2f',
                color: '#ffffff',
                '&:hover': { backgroundColor: '#3f3f3f' },
                '&.Mui-disabled': { backgroundColor: 'rgba(47,47,47,0.5)' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={authLoading ? <CircularProgress size={20} color="inherit" /> : <svg width="20" height="20" viewBox="0 0 23 23"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M12 1h10v10H12z"/><path fill="#05a6f0" d="M1 12h10v10H1z"/><path fill="#ffba08" d="M12 12h10v10H12z"/></svg>}
            >
              Sign in with Microsoft
            </Button>
          </Stack>

          <Divider sx={{ my: 1 }}><Typography variant="caption" color="text.secondary">OR ENTER EMAIL</Typography></Divider>

          {/* Email Input Form */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, textAlign: 'left' }}>
            <TextField
              label="Work or Personal Email"
              fullWidth
              size="small"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleEmailLogin()}
              placeholder="e.g. dev@company.com"
            />

            {email && email.includes('@') && (
              <Alert severity={tenancy.isGeneric ? "warning" : "success"} sx={{ borderRadius: 2, fontSize: '0.8rem' }}>
                <strong>Tenancy Auto-Resolution:</strong> {tenancy.isGeneric ? 'Generic Public Provider' : 'Corporate Domain'} &rarr; Org Realm: <code style={{ fontWeight: 700 }}>{tenancy.orgId}</code>
              </Alert>
            )}

            <Button
              variant="contained"
              color="primary"
              size="large"
              fullWidth
              disabled={!email || !email.includes('@')}
              endIcon={<ArrowForwardIcon />}
              onClick={handleEmailLogin}
              sx={{ py: 1.2, fontWeight: 700 }}
            >
              Log In & Enter Civilization
            </Button>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
}
