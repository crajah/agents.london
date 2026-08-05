import React, { useState } from 'react';
import { Box, Paper, Typography, Button, TextField, List, ListItem, ListItemButton, ListItemText, Divider, Stack } from '@mui/material';
import PsychologyIcon from '@mui/icons-material/Psychology';
import SearchIcon from '@mui/icons-material/Search';

export default function SharedMemoryView({ state }) {
  const [query, setQuery] = useState('');
  const activeProject = state?.projectId || 'proj_alpha_civilization';

  const [results, setResults] = useState([
    { doc: `spec_${activeProject}.pdf`, page: 1, text: `All agents operating in session memory share context vector embeddings and post-graph edge relations under realm '${activeProject}'.` }
  ]);

  const handleQuery = () => {
    if (!query.trim()) return;
    setResults(prev => [
      { doc: `agent_constitution_${activeProject}.pdf`, page: 3, text: `Vector search matched query '${query}' with 0.94 similarity in post-graph-rag session memory for project '${activeProject}'.` },
      ...prev
    ]);
    setQuery('');
  };

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Shared Session Memory & RAG Knowledge Store ({activeProject})
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Segregated session memory context created for multi-agent collaboration in project realm <code>{activeProject}</code> using post-graph-rag.
          </Typography>
        </Box>

        <Button
          variant="contained"
          color="primary"
          onClick={async () => {
            try {
              const sessionName = `collab_${Date.now()}`;
              await fetch('/api/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  org_id: state?.orgId || 'org_london_meta',
                  project_id: activeProject,
                  user_id: state?.userId || 'user_chandan',
                  session_name: sessionName
                })
              });
            } catch (e) {
              console.error('Session initiation error:', e);
            }
          }}
        >
          + Initiate New Session in {activeProject}
        </Button>
      </Box>

      {/* Main Sessions Layout */}
      <Box sx={{ display: 'flex', gap: 3, minHeight: 450, flexWrap: 'wrap' }}>
        {/* Left Session List */}
        <Paper sx={{ width: 300, p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            Active Collaboration Sessions ({activeProject})
          </Typography>

          <List disablePadding>
            <ListItem disablePadding>
              <ListItemButton selected sx={{ borderRadius: 2 }}>
                <ListItemText
                  primary={`#sess_${activeProject}_collab`}
                  secondary="8 Agents • post-graph-rag active"
                  primaryTypographyProps={{ fontSize: '0.85rem', fontWeight: 600, color: '#60a5fa' }}
                  secondaryTypographyProps={{ fontSize: '0.72rem' }}
                />
              </ListItemButton>
            </ListItem>
          </List>
        </Paper>

        {/* Right Memory Inspector */}
        <Paper sx={{ flex: 1, p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            Session Knowledge Snippets (post-graph-rag Memory Engine)
          </Typography>

          <Box sx={{ flex: 1, overflowY: 'auto', p: 2, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.7)', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {results.map((r, idx) => (
              <Paper key={idx} elevation={0} sx={{ p: 2, backgroundColor: 'rgba(19, 27, 46, 0.6)', borderLeft: '4px solid #3b82f6' }}>
                <Typography variant="caption" sx={{ color: '#60a5fa', fontFamily: '"JetBrains Mono", monospace' }}>
                  [Document: {r.doc} | Page: {r.page}]
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {r.text}
                </Typography>
              </Paper>
            ))}
          </Box>

          <Stack direction="row" spacing={1.5}>
            <TextField
              fullWidth
              size="small"
              placeholder="Query shared session memory via post-graph-rag..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
            />
            <Button variant="contained" color="primary" startIcon={<SearchIcon />} onClick={handleQuery} sx={{ px: 3 }}>
              Query
            </Button>
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
}
