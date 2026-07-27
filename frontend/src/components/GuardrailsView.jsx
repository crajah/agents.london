import React from 'react';
import { Box, Paper, Typography, Grid, Card, CardContent, Chip, Stack } from '@mui/material';
import ShieldIcon from '@mui/icons-material/Shield';
import GavelIcon from '@mui/icons-material/Gavel';

export default function GuardrailsView({ state }) {
  const activeProject = state?.projectId || 'proj_alpha_civilization';

  const guardrails = [
    {
      id: 'g1',
      title: 'Rule 1: Destructive Command Execution Block',
      desc: `Agents operating in project '${activeProject}' are strictly forbidden from running unverified destructive filesystem or database mutation commands.`,
      source: `Project Constitution (${activeProject})`,
      enforcer: 'InspectorAgent',
      badge: 'INVIOLABLE'
    },
    {
      id: 'g2',
      title: 'Rule 2: Cryptographic Identity Signature Verification',
      desc: `All inter-agent messages and Kagent progeny materialization requests in '${activeProject}' must be cryptographically signed via ED25519.`,
      source: 'Civilization Core Directives',
      enforcer: 'JudicatureNode',
      badge: 'INVIOLABLE'
    },
    {
      id: 'g3',
      title: 'Rule 3: Multi-Tenant Realm Isolation',
      desc: `Agents operating in project realm '${activeProject}' cannot read or modify vector embeddings or post-graph edges in any other project realm.`,
      source: 'Multi-Tenant Security Spec',
      enforcer: 'OntologicalRegistry',
      badge: 'STRICT ISOLATION'
    }
  ];

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Constitutional Guardrails & Inspector Agent Audits ({activeProject})
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Inviolable safety rules discovered from user prompts or explicitly declared in Org/Project constitutions for realm <code>{activeProject}</code>.
        </Typography>
      </Box>

      <Grid container spacing={2.5}>
        {guardrails.map((g) => (
          <Grid item xs={12} md={4} key={g.id}>
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', borderLeft: '4px solid #ef4444' }}>
              <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Chip label={g.badge} size="small" color="error" sx={{ fontWeight: 800, fontSize: '0.65rem' }} />
                  <GavelIcon sx={{ fontSize: 18, color: '#ef4444' }} />
                </Stack>

                <Typography variant="h6" sx={{ fontSize: '1rem', fontWeight: 700 }}>
                  {g.title}
                </Typography>

                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.85rem', flex: 1 }}>
                  {g.desc}
                </Typography>

                <Box sx={{ pt: 1, borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: 'text.secondary' }}>
                  <span>Source: <strong>{g.source}</strong> | Enforcer: <strong style={{ color: '#3b82f6' }}>{g.enforcer}</strong></span>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
