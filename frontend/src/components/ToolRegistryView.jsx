import React, { useState } from 'react';
import {
  Box, Paper, Typography, Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Chip, Grid, Card, CardContent, Stack
} from '@mui/material';
import BuildIcon from '@mui/icons-material/Build';
import AddIcon from '@mui/icons-material/Add';
import MemoryIcon from '@mui/icons-material/Memory';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RegisterToolModal from './RegisterToolModal';

export default function ToolRegistryView({ state, onAddTool }) {
  const [registerModalOpen, setRegisterModalOpen] = useState(false);

  const availableModels = state.availableModels || [
    { id: 'gemini-1.5-pro', name: 'Google Gemini 1.5 Pro', provider: 'Google DeepMind', context_window: 1048576, status: 'ACTIVE' },
    { id: 'gpt-4o', name: 'OpenAI GPT-4o', provider: 'OpenAI', context_window: 128000, status: 'ACTIVE' },
    { id: 'claude-3-5-sonnet', name: 'Anthropic Claude 3.5 Sonnet', provider: 'Anthropic', context_window: 200000, status: 'ACTIVE' },
    { id: 'mistral-large', name: 'Mistral Large 2', provider: 'Mistral AI', context_window: 128000, status: 'ACTIVE' },
    { id: 'llama-3-70b', name: 'Meta Llama 3 70B', provider: 'Meta AI', context_window: 8192, status: 'ACTIVE' }
  ];

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Model Context Protocol (MCP) Tool Registry & Model Router
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Register new MCP tools and inspect active LiteLLM model router endpoints.
          </Typography>
        </Box>

        <Button
          variant="contained"
          color="primary"
          startIcon={<AddIcon />}
          onClick={() => setRegisterModalOpen(true)}
        >
          Register MCP Tool
        </Button>
      </Box>

      {/* Available Models Panel */}
      <Paper sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1, color: '#60a5fa' }}>
          <MemoryIcon sx={{ fontSize: 20 }} /> Available LLM Router Endpoints (/v1/models)
        </Typography>

        <Grid container spacing={2}>
          {availableModels.map((m) => (
            <Grid item xs={12} sm={6} md={2.4} key={m.id}>
              <Card sx={{ backgroundColor: 'rgba(9, 13, 22, 0.7)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                    <Chip label={m.status} size="small" color="success" sx={{ height: 16, fontSize: '0.6rem', fontWeight: 700 }} />
                    <CheckCircleIcon sx={{ fontSize: 14, color: '#10b981' }} />
                  </Stack>

                  <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: '0.85rem' }}>
                    {m.name}
                  </Typography>

                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: '0.72rem' }}>
                    {m.provider}
                  </Typography>

                  <Box sx={{ mt: 1, pt: 1, borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'text.secondary' }}>
                    <span>Context: <strong>{typeof m.context_window === 'number' ? m.context_window.toLocaleString() : (m.context || '128,000')}</strong></span>
                    <span>Status: <strong style={{ color: '#10b981' }}>{m.status || 'ACTIVE'}</strong></span>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Paper>

      {/* MCP Tools Table */}
      <TableContainer component={Paper}>
        <Table sx={{ minWidth: 650 }}>
          <TableHead sx={{ backgroundColor: 'rgba(9, 13, 22, 0.8)' }}>
            <TableRow>
              <TableCell sx={{ fontWeight: 700 }}>Tool ID</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Name</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Scope</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Endpoint URL</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Input Schema</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {state.tools.map((t) => (
              <TableRow key={t.tool_id} hover>
                <TableCell sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: '0.85rem' }}>{t.tool_id}</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>{t.name}</TableCell>
                <TableCell>
                  <Chip label={t.scope_type.toUpperCase()} size="small" color={t.scope_type === 'org' ? 'primary' : 'secondary'} sx={{ fontSize: '0.65rem', fontWeight: 700 }} />
                </TableCell>
                <TableCell sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: '0.8rem', color: '#60a5fa' }}>{t.endpoint_url}</TableCell>
                <TableCell sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: '0.75rem', color: 'text.secondary' }}>
                  {JSON.stringify(t.input_schema)}
                </TableCell>
                <TableCell>
                  <Button variant="outlined" size="small" sx={{ fontSize: '0.75rem' }}>
                    Inspect
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Register Tool Modal */}
      <RegisterToolModal
        open={registerModalOpen}
        onClose={() => setRegisterModalOpen(false)}
        onRegisterTool={onAddTool}
      />
    </Box>
  );
}
