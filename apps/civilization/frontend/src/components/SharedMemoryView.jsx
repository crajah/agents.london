import React, { useEffect, useState } from 'react';
import { api, attempt } from '../utils/api';
import {
  Box, Paper, Typography, Button, TextField, List, ListItem, ListItemButton,
  ListItemText, Stack, Alert, Chip, CircularProgress, Tooltip,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import RefreshIcon from '@mui/icons-material/Refresh';

/**
 * What a run wrote to shared context, in the order it wrote it.
 *
 * The panel used to show one invented session and a fixed "8 Agents". The
 * registry records something better and real: every revision of every context
 * key, each stamped with the step that wrote it. Revisions are kept rather than
 * overwritten so a cyclic run can be read back afterwards (AG Rule 8.5), and
 * collapsing them to a final value throws away the second pass through a loop —
 * which is usually the pass you opened this panel to look at (F.33).
 */
export default function SharedMemoryView({ state }) {
  const activeProject = state?.projectId || null;

  const [runs, setRuns] = useState([]);
  const [runsError, setRunsError] = useState(null);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRun, setSelectedRun] = useState(null);

  const [context, setContext] = useState(null);
  const [contextError, setContextError] = useState(null);
  const [loadingContext, setLoadingContext] = useState(false);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [queryError, setQueryError] = useState(null);
  const [querying, setQuerying] = useState(false);

  const loadRuns = async () => {
    setLoadingRuns(true);
    const { data, error } = await attempt(api.get('/api/runs', { params: { limit: 40 } }));
    setLoadingRuns(false);
    if (error) { setRunsError(error); setRuns([]); return; }
    setRunsError(null);
    const list = data?.runs || [];
    setRuns(list);
    // Keep whatever was selected if it survived the refresh, otherwise open
    // the newest run, which is nearly always the one being investigated.
    setSelectedRun((current) => {
      if (current && list.some((r) => r.pk === current)) return current;
      return list.length ? list[0].pk : null;
    });
  };

  useEffect(() => { loadRuns(); }, [activeProject, state?.orgId]);

  useEffect(() => {
    if (selectedRun == null) { setContext(null); return; }
    let cancelled = false;
    (async () => {
      setLoadingContext(true);
      const { data, error } = await attempt(api.get(`/api/runs/${selectedRun}/context`,
                                                    { scoped: false }));
      if (cancelled) return;
      setLoadingContext(false);
      if (error) { setContextError(error); setContext(null); return; }
      setContextError(null);
      setContext(data);
    })();
    return () => { cancelled = true; };
  }, [selectedRun]);

  const handleQuery = async () => {
    if (!query.trim() || !activeProject) return;
    setQuerying(true);
    const { data, error } = await attempt(
      api.post(`/api/projects/${activeProject}/rag/query`, undefined, { params: { query } }));
    setQuerying(false);
    if (error) { setQueryError(error); setResults([]); return; }
    setQueryError(null);
    const chunks = data?.data?.chunks || data?.chunks || [];
    setResults(chunks.map((c, i) => ({
      doc: c.metadata?.document || c.metadata?.doc_key || `chunk_${i}`,
      page: c.metadata?.page ?? null,
      text: c.content || '',
    })));
  };

  const revisions = context?.revisions || [];
  const conflicts = context?.conflicts || [];

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Shared session memory
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Every context revision a run wrote, oldest first, in project{' '}
            <code>{activeProject || '—'}</code>.
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadRuns} disabled={loadingRuns}>
          {loadingRuns ? 'Loading…' : 'Refresh runs'}
        </Button>
      </Box>

      <Box sx={{ display: 'flex', gap: 3, minHeight: 450, flexWrap: 'wrap' }}>
        <Paper sx={{ width: 320, p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            Runs ({runs.length})
          </Typography>

          {runsError && <Alert severity="error" sx={{ fontSize: '0.75rem' }}>{runsError.userMessage}</Alert>}
          {!runsError && !loadingRuns && runs.length === 0 && (
            <Alert severity="info" sx={{ fontSize: '0.75rem' }}>
              No pipeline has run in this project yet.
            </Alert>
          )}

          <List disablePadding sx={{ overflowY: 'auto' }}>
            {runs.map((run) => (
              <ListItem key={run.pk} disablePadding>
                <ListItemButton
                  selected={run.pk === selectedRun}
                  onClick={() => setSelectedRun(run.pk)}
                  sx={{ borderRadius: 2 }}
                >
                  <ListItemText
                    primary={run.run_id || `run ${run.pk}`}
                    secondary={[run.pipeline_id, run.status, run.started_at]
                      .filter(Boolean).join(' • ')}
                    primaryTypographyProps={{ fontSize: '0.8rem', fontWeight: 600, color: '#60a5fa' }}
                    secondaryTypographyProps={{ fontSize: '0.7rem' }}
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        </Paper>

        <Paper sx={{ flex: 1, minWidth: 380, p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            Context revisions {selectedRun != null && <code>· run {selectedRun}</code>}
          </Typography>

          {contextError && <Alert severity="error">{contextError.userMessage}</Alert>}
          {loadingContext && <CircularProgress size={20} />}
          {!loadingContext && !contextError && selectedRun != null && revisions.length === 0 && (
            <Alert severity="info" sx={{ fontSize: '0.8rem' }}>
              This run wrote no shared context.
            </Alert>
          )}

          {conflicts.length > 0 && (
            <Alert severity="warning" sx={{ fontSize: '0.78rem' }}>
              {conflicts.length} concurrent write{conflicts.length === 1 ? '' : 's'} to the same key.
              The last writer won; the overwritten revision is still listed above.
            </Alert>
          )}

          <Box sx={{ flex: 1, overflowY: 'auto', p: 2, borderRadius: 2, backgroundColor: 'rgba(9, 13, 22, 0.7)', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {/* Oldest first. A later revision of the same key does not replace
                the earlier one on screen — that ordering is the whole point. */}
            {revisions.map((rev, idx) => (
              <Paper key={`${rev.key}-${rev.revision}-${idx}`} elevation={0}
                     sx={{ p: 2, backgroundColor: 'rgba(19, 27, 46, 0.6)', borderLeft: '4px solid #3b82f6' }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                  <Chip label={`rev ${rev.revision ?? idx + 1}`} size="small" color="primary"
                        sx={{ height: 18, fontSize: '0.62rem', fontWeight: 700 }} />
                  <Typography variant="caption" sx={{ color: '#60a5fa', fontFamily: '"JetBrains Mono", monospace' }}>
                    {rev.key}
                  </Typography>
                  {rev.written_by && (
                    <Tooltip title="The step that wrote this revision">
                      <Chip label={rev.written_by} size="small" variant="outlined"
                            sx={{ height: 18, fontSize: '0.62rem' }} />
                    </Tooltip>
                  )}
                  {rev.written_at && (
                    <Typography variant="caption" sx={{ color: '#94a3b8' }}>{rev.written_at}</Typography>
                  )}
                </Stack>
                <Typography variant="body2" sx={{ mt: 0.75, whiteSpace: 'pre-wrap', fontFamily: '"JetBrains Mono", monospace', fontSize: '0.76rem' }}>
                  {typeof rev.value === 'string' ? rev.value : JSON.stringify(rev.value, null, 2)}
                </Typography>
              </Paper>
            ))}

            {conflicts.map((conflict, idx) => (
              <Paper key={`conflict-${idx}`} elevation={0}
                     sx={{ p: 2, backgroundColor: 'rgba(46, 27, 19, 0.6)', borderLeft: '4px solid #f59e0b' }}>
                <Typography variant="caption" sx={{ color: '#f59e0b', fontFamily: '"JetBrains Mono", monospace' }}>
                  conflict on {conflict.key}
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5, fontSize: '0.76rem' }}>
                  <code>{conflict.writer}</code> overwrote{' '}
                  <code>{conflict.previous_writer}</code> — last write won, and both
                  values remain in the revision list above.
                </Typography>
              </Paper>
            ))}
          </Box>
        </Paper>
      </Box>

      <Paper sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          Query the project knowledge store
        </Typography>
        {queryError && <Alert severity="error">{queryError.userMessage}</Alert>}
        {!queryError && !querying && results.length === 0 && query === '' && (
          <Typography variant="caption" color="text.secondary">
            Retrieval runs against this project’s documents via post-graph-rag.
          </Typography>
        )}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {results.map((r, idx) => (
            <Paper key={idx} elevation={0} sx={{ p: 2, backgroundColor: 'rgba(19, 27, 46, 0.6)', borderLeft: '4px solid #10b981' }}>
              <Typography variant="caption" sx={{ color: '#34d399', fontFamily: '"JetBrains Mono", monospace' }}>
                {r.doc}{r.page != null ? ` · page ${r.page}` : ''}
              </Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>{r.text}</Typography>
            </Paper>
          ))}
        </Box>
        <Stack direction="row" spacing={1.5}>
          <TextField
            fullWidth
            size="small"
            placeholder="Search this project's documents…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
          />
          <Button variant="contained" color="primary" startIcon={<SearchIcon />}
                  onClick={handleQuery} disabled={querying || !activeProject} sx={{ px: 3 }}>
            {querying ? 'Searching…' : 'Query'}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}
