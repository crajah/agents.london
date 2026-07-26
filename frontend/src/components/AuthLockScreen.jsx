import React, { useState } from 'react';
import {
  Box, Paper, Typography, Button, TextField, Chip, Stack, Link, Container, Divider, Alert
} from '@mui/material';
import LockIcon from '@mui/icons-material/Lock';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import HubIcon from '@mui/icons-material/Hub';

const GENERIC_EMAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
  "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
  "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
  "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
  "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
]);

export default function AuthLockScreen({ onAuthenticate }) {
  const [email, setEmail] = useState('chandan@gmail.com');

  const resolveTenancy = (rawEmail) => {
    if (!rawEmail || !rawEmail.includes('@')) {
      return { userPart: 'chandan', domainPart: 'gmail.com', orgId: 'org_user_chandan_gmail_com', isGeneric: true, clean: 'chandan@gmail.com' };
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

  const handleLoginSubmit = (targetEmail) => {
    const finalEmail = targetEmail || email;
    const resolved = resolveTenancy(finalEmail);
    onAuthenticate({
      email: resolved.clean,
      orgId: resolved.orgId,
      userId: `user_${resolved.userPart}`,
      isGeneric: resolved.isGeneric
    });
  };

  return (
    <Box sx={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'radial-gradient(circle at 50% 20%, rgba(59, 130, 246, 0.15) 0%, rgba(11, 15, 25, 1) 70%)',
      p: 2
    }}>
      <Container maxWidth="sm">
        <Paper sx={{ p: 4, display: 'flex', flexDirection: 'column', gap: 3, textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
          {/* Top Brand Logo */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
            <Typography variant="h1" sx={{ fontSize: '3rem', mb: -1 }}>🏛️</Typography>
            <Typography variant="h3" sx={{
              fontWeight: 800,
              background: 'linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              letterSpacing: '-1px'
            }}>
              agent.london
            </Typography>
            <Chip label="1B Agent Civilization Engine" color="primary" size="small" sx={{ fontWeight: 700, fontSize: '0.75rem' }} />
            
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
              Brainchild of <Link href="https://www.linkedin.com/in/crajah/" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa', fontWeight: 600 }}>Chandan Rajah</Link> (<Link href="https://github.com/crajah" target="_blank" rel="noopener" underline="hover" sx={{ color: '#60a5fa' }}>GitHub</Link>)
            </Typography>
          </Box>

          <Typography variant="body1" color="text.secondary" sx={{ fontSize: '0.95rem', px: 2 }}>
            Authentication required to enter the multi-tenant agent civilization universe. Sign in or register to instantiate your realm.
          </Typography>

          {/* SSO Action Buttons */}
          <Stack spacing={1.5}>
            <Button
              variant="contained"
              fullWidth
              size="large"
              onClick={() => {
                const testEmail = prompt("Google Identity OAuth - Enter Email:", "chandan@gmail.com");
                if (testEmail) handleLoginSubmit(testEmail);
              }}
              sx={{
                backgroundColor: '#ffffff',
                color: '#1f2937',
                '&:hover': { backgroundColor: '#f9fafb' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={<svg width="20" height="20" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>}
            >
              Sign in with Google Identity
            </Button>

            <Button
              variant="contained"
              fullWidth
              size="large"
              onClick={() => {
                const testEmail = prompt("Microsoft Identity OAuth - Enter Email:", "chandan@outlook.com");
                if (testEmail) handleLoginSubmit(testEmail);
              }}
              sx={{
                backgroundColor: '#2f2f2f',
                color: '#ffffff',
                '&:hover': { backgroundColor: '#3f3f3f' },
                fontWeight: 700,
                py: 1.2
              }}
              startIcon={<svg width="20" height="20" viewBox="0 0 23 23"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M12 1h10v10H12z"/><path fill="#05a6f0" d="M1 12h10v10H1z"/><path fill="#ffba08" d="M12 12h10v10H12z"/></svg>}
            >
              Sign in with Microsoft Identity
            </Button>
          </Stack>

          <Divider sx={{ my: 1 }}><Typography variant="caption" color="text.secondary">OR REGISTER WITH ANY EMAIL</Typography></Divider>

          {/* Email Input Form */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, textAlign: 'left' }}>
            <TextField
              label="Work or Personal Email"
              fullWidth
              size="small"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. chandan@gmail.com or dev@company.com"
            />

            <Alert severity={tenancy.isGeneric ? "warning" : "success"} sx={{ borderRadius: 2, fontSize: '0.8rem' }}>
              <strong>Tenancy Auto-Resolution:</strong> {tenancy.isGeneric ? 'Generic Public Provider' : 'Corporate Domain'} &rarr; Org Realm: <code style={{ fontWeight: 700 }}>{tenancy.orgId}</code>
            </Alert>

            <Button
              variant="contained"
              color="primary"
              size="large"
              fullWidth
              endIcon={<ArrowForwardIcon />}
              onClick={() => handleLoginSubmit(email)}
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
