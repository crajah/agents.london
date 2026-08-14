import React, { useEffect, useState } from 'react';
import { api, attempt } from '../utils/api';
import {
  Box, Typography, Grid, Card, CardContent, Chip, Stack, Alert, CircularProgress,
} from '@mui/material';
import GavelIcon from '@mui/icons-material/Gavel';

/**
 * The constraints this project's agents actually carry.
 *
 * The panel used to render three rules written into this file — a destructive
 * command block, a signature requirement, a realm isolation clause — with the
 * project name interpolated so they read as though they had been discovered
 * from that project's constitution. None of them came from anywhere. A safety
 * panel that invents safety is worse than an empty one.
 *
 * These come from the agents themselves: a guardrail is recorded on the agent
 * it binds, with a level and a source (a constitution, or the prompt the agent
 * was materialised from).
 */
export default function GuardrailsView({ state }) {
  const activeProject = state?.projectId || null;

  const [guardrails, setGuardrails] = useState([]);
  const [scanned, setScanned] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activeProject) return undefined;
    let cancelled = false;
    (async () => {
      setLoading(true);
      const { data, error: err } = await attempt(
        api.get(`/api/projects/${activeProject}/guardrails`, { scoped: false }));
      if (cancelled) return;
      setLoading(false);
      if (err) { setError(err); setGuardrails([]); return; }
      setError(null);
      setGuardrails(data?.guardrails || []);
      setScanned(data?.agents_scanned || 0);
    })();
    return () => { cancelled = true; };
  }, [activeProject, state?.orgId]);

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Guardrails
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Rules attached to the agents in <code>{activeProject || '—'}</code>
          {scanned > 0 && <> · {scanned} agent{scanned === 1 ? '' : 's'} scanned</>}
        </Typography>
      </Box>

      {loading && <CircularProgress size={22} />}
      {error && <Alert severity="error">{error.userMessage}</Alert>}
      {!loading && !error && guardrails.length === 0 && (
        <Alert severity="info">
          No agent in this project carries a guardrail. Guardrails are attached
          when an agent is materialised, from a constitution or from the prompt
          that created it.
        </Alert>
      )}

      <Grid container spacing={2.5}>
        {guardrails.map((g) => (
          <Grid item xs={12} md={4} key={g.guardrail_id || g.rule}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', borderLeft: '4px solid #ef4444' }}>
              <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Chip
                    label={(g.level || 'unscoped').toUpperCase()}
                    size="small"
                    color={g.level === 'org' ? 'error' : 'warning'}
                    sx={{ fontWeight: 800, fontSize: '0.65rem' }}
                  />
                  <GavelIcon sx={{ fontSize: 18, color: '#ef4444' }} />
                </Stack>

                <Typography variant="body1" sx={{ fontSize: '0.92rem', fontWeight: 600, flex: 1 }}>
                  {g.rule}
                </Typography>

                <Box sx={{ pt: 1, borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: 'text.secondary', display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                  <span>Source: <strong>{g.source || 'unrecorded'}</strong></span>
                  {/* "Blocked and audited" and "logged" are different promises.
                      Nothing records which this is, so nothing claims it (F.34). */}
                  <span>
                    On violation:{' '}
                    <strong style={{ color: g.action ? '#3b82f6' : '#f59e0b' }}>
                      {g.action || 'not recorded'}
                    </strong>
                  </span>
                  {g.bound_agents?.length > 0 && (
                    <span>Binds: <strong>{g.bound_agents.join(', ')}</strong></span>
                  )}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
