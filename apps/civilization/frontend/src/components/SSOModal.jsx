import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Typography, Box, Divider, Alert,
  CircularProgress
} from '@mui/material';

import { triggerGoogleOIDC, triggerMicrosoftOIDC } from '../utils/oidc';

const GENERIC_EMAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
  "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
  "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
  "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
  "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
]);

export default function SSOModal({ open, onClose, onLoginSuccess }) {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const resolveTenancy = (rawEmail) => {
    if (!rawEmail || !rawEmail.includes('@')) {
      return { userPart: 'user', domainPart: 'unknown', orgId: 'org_unknown', isGeneric: true };
    }
    const clean = rawEmail.toLowerCase().trim();
    const parts = clean.split('@');
    const userPart = parts[0].replace(/[^a-z0-9]/g, '_');
    const domainPart = parts[1];
    const sanitizedDomain = domainPart.replace(/[^a-z0-9]/g, '_');

    const isGeneric = GENERIC_EMAIL_DOMAINS.has(domainPart);
    const orgId = isGeneric ? `org_user_${userPart}_${sanitizedDomain}` : `org_${sanitizedDomain}`;
    return { userPart, domainPart, orgId, isGeneric, clean };
  };

  const tenancy = resolveTenancy(email);

  const handleOAuthSuccess = (session) => {
    setLoading(false);
    setError(null);
    onLoginSuccess(session.email);
    onClose();
  };

  const handleOAuthError = (errorMsg) => {
    setLoading(false);
    setError(errorMsg);
  };

  const handleEmailLogin = () => {
    if (!email || !email.includes('@')) return;
    onLoginSuccess(email);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ fontWeight: 700, pb: 1 }}>
        SSO Identity Login (Google / Microsoft)
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Log in with Google or Microsoft Identity. Generic email providers (Gmail, Outlook, Yahoo) generate a synthetic Organization for your specific email address.
        </Typography>

        {/* Error Display */}
        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ borderRadius: 2 }}>
            {error}
          </Alert>
        )}

        {/* SSO Action Buttons */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Button
            variant="contained"
            fullWidth
            disabled={loading}
            onClick={() => {
              setLoading(true);
              setError(null);
              triggerGoogleOIDC(handleOAuthSuccess, handleOAuthError);
            }}
            sx={{
              backgroundColor: '#ffffff',
              color: '#1f2937',
              '&:hover': { backgroundColor: '#f9fafb' },
              '&.Mui-disabled': { backgroundColor: 'rgba(255,255,255,0.3)' },
              fontWeight: 600
            }}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/></svg>}
          >
            Sign in with Google
          </Button>

          <Button
            variant="contained"
            fullWidth
            disabled={loading}
            onClick={() => {
              setLoading(true);
              setError(null);
              triggerMicrosoftOIDC(handleOAuthSuccess, handleOAuthError).catch(handleOAuthError);
            }}
            sx={{
              backgroundColor: '#2f2f2f',
              color: '#ffffff',
              '&:hover': { backgroundColor: '#3f3f3f' },
              '&.Mui-disabled': { backgroundColor: 'rgba(47,47,47,0.5)' },
              fontWeight: 600
            }}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <svg width="18" height="18" viewBox="0 0 23 23"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M12 1h10v10H12z"/><path fill="#05a6f0" d="M1 12h10v10H1z"/><path fill="#ffba08" d="M12 12h10v10H12z"/></svg>}
          >
            Sign in with Microsoft
          </Button>
        </Box>

        <Divider sx={{ my: 1 }}><Typography variant="caption" color="text.secondary">OR ENTER EMAIL</Typography></Divider>

        <TextField
          label="Work or Personal Email"
          size="small"
          fullWidth
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleEmailLogin()}
        />

        {/* Live Classification Preview */}
        {email && email.includes('@') && (
          <Alert severity={tenancy.isGeneric ? "warning" : "success"} sx={{ borderRadius: 2, fontSize: '0.8rem' }}>
            <strong>Tenancy Preview:</strong> {tenancy.isGeneric ? 'Generic Provider' : 'Corporate Domain'} &rarr; Org: <code style={{ fontWeight: 700 }}>{tenancy.orgId}</code>
          </Alert>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        <Button
          onClick={handleEmailLogin}
          variant="contained"
          color="primary"
          disabled={!email || !email.includes('@')}
        >
          Log In & Instantiate Org
        </Button>
      </DialogActions>
    </Dialog>
  );
}
