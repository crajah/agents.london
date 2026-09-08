import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, IconButton, Box, Paper, Typography,
  Chip, Stack, Divider, Collapse, Button, Tooltip, Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import SouthIcon from '@mui/icons-material/South';
import PersonIcon from '@mui/icons-material/Person';
import BookmarkAddIcon from '@mui/icons-material/BookmarkAdd';
import AutoFormatDetectorRenderer from './AutoFormatDetectorRenderer';

/**
 * How an answer was built.
 *
 * The final answer is the answer — but a composition is a claim about work,
 * and this is where the claim is inspected. Every stage the run executed is an
 * agent that received a message and produced one; the message it received was
 * the message the agent before it produced. That handoff IS the agent-to-agent
 * exchange, so this renders the run as an A2A chain: node, handoff, node — and
 * each node opens to the exact context it was handed and the exact context it
 * passed on. Nothing here is reconstructed; it is the input and output the
 * stream reported at the moment each agent ran.
 *
 * A proven combination can be catalogued as a single reusable agent from the
 * footer — a pipeline of agents is a pipeline of one.
 */

function Pin({ version, hash }) {
  if (!version) return null;
  return (
    <Tooltip title={hash || 'no content hash recorded'}>
      <Typography variant="caption"
                  sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#a78bfa' }}>
        v{version}{hash && ` · ${String(hash).slice(7, 17)}`}
      </Typography>
    </Tooltip>
  );
}

function AgentNode({ stage, index, isEntry, isExit }) {
  const [open, setOpen] = useState(false);
  const failed = stage.status === 'failed' || stage.failed;
  const received = stage.input;
  const produced = stage.output;

  return (
    <Paper elevation={0} sx={{
      borderRadius: 2, overflow: 'hidden',
      border: `1px solid ${failed ? 'rgba(239,68,68,0.4)' : 'rgba(56,189,248,0.25)'}`,
      bgcolor: 'rgba(9, 13, 22, 0.7)',
    }}>
      <Box onClick={() => setOpen((v) => !v)}
           sx={{ p: 1.75, cursor: 'pointer', '&:hover': { bgcolor: 'rgba(56,189,248,0.05)' } }}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <PersonIcon sx={{ fontSize: 18, color: failed ? '#ef4444' : '#38bdf8' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#e2e8f0' }}>
            {index + 1}. {stage.agent_name || stage.agent || stage.step}
          </Typography>
          {isEntry && <Chip size="small" label="entry" sx={{ height: 17, fontSize: '0.58rem' }} />}
          {isExit && <Chip size="small" color="success" label="deliverable" sx={{ height: 17, fontSize: '0.58rem' }} />}
          <Box sx={{ flex: 1 }} />
          <Pin version={stage.version} hash={stage.content_hash} />
          {stage.duration_ms != null && (
            <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 700 }}>
              {stage.duration_ms}ms
            </Typography>
          )}
          {open ? <ExpandLessIcon sx={{ fontSize: 18, color: '#64748b' }} />
                : <ExpandMoreIcon sx={{ fontSize: 18, color: '#64748b' }} />}
        </Stack>
        {stage.need && (
          <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mt: 0.5, ml: 3.25 }}>
            {stage.need}
          </Typography>
        )}
      </Box>

      <Collapse in={open} unmountOnExit>
        <Divider sx={{ borderColor: 'rgba(255,255,255,0.06)' }} />
        <Box sx={{ p: 1.75, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Box>
            <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 700,
                        textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Context received
            </Typography>
            <Paper elevation={0} sx={{ p: 1.25, mt: 0.5, bgcolor: 'rgba(0,0,0,0.3)', borderRadius: 1.5 }}>
              {received
                ? <AutoFormatDetectorRenderer content={String(received)} />
                : <Typography variant="caption" sx={{ color: '#64748b' }}>
                    Nothing recorded (this agent opened the chain).
                  </Typography>}
            </Paper>
          </Box>
          <Box>
            <Typography variant="caption" sx={{ color: '#10b981', fontWeight: 700,
                        textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Context produced
            </Typography>
            <Paper elevation={0} sx={{ p: 1.25, mt: 0.5, bgcolor: 'rgba(0,0,0,0.3)', borderRadius: 1.5 }}>
              {failed
                ? <Alert severity="error" sx={{ fontSize: '0.78rem' }}>
                    {stage.error || 'This agent failed and the chain halted here.'}
                  </Alert>
                : produced
                  ? <AutoFormatDetectorRenderer content={String(produced)} />
                  : <Typography variant="caption" sx={{ color: '#64748b' }}>
                      No output recorded.
                    </Typography>}
            </Paper>
          </Box>
        </Box>
      </Collapse>
    </Paper>
  );
}

export default function RunDetailModal({ run, open, onClose, onCatalogue }) {
  if (!run) return null;
  const stages = run.stages || [];
  const answered = run.answer && !run.answer.failed && !run.answer.refused;
  const catalogable = answered && stages.length >= 1
    && (run.pipeline?.mcp_tool || run.answer?.mcp_tool);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth
            PaperProps={{ sx: { bgcolor: '#0b0f16', backgroundImage: 'none',
                                border: '1px solid rgba(56,189,248,0.2)' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 6 }}>
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>How this answer was built</Typography>
          <Typography variant="caption" sx={{ color: '#94a3b8' }}>
            {stages.length} agent{stages.length === 1 ? '' : 's'} combined over A2A
            {run.answer?.duration_ms != null && ` · ${(run.answer.duration_ms / 1000).toFixed(1)}s`}
          </Typography>
        </Box>
        <IconButton onClick={onClose} sx={{ position: 'absolute', right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ borderColor: 'rgba(255,255,255,0.08)' }}>
        {/* The goal */}
        {run.prompt && (
          <Paper elevation={0} sx={{ p: 1.5, mb: 2, borderRadius: 2,
                 bgcolor: 'rgba(15,23,42,0.6)' }}>
            <Typography variant="caption" sx={{ color: '#64748b', textTransform: 'uppercase',
                        letterSpacing: '0.08em', fontWeight: 700 }}>The goal</Typography>
            <Typography variant="body2" sx={{ color: '#e2e8f0', mt: 0.25 }}>{run.prompt}</Typography>
          </Paper>
        )}

        {/* Who routed it */}
        {run.intake && (
          <Paper elevation={0} sx={{ p: 1.5, mb: 2, borderRadius: 2, bgcolor: 'rgba(15,23,42,0.6)' }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#38bdf8' }}>
                The Intake Praetor
              </Typography>
              {run.intake.route && <Chip size="small" color="secondary" label={run.intake.route}
                                         sx={{ height: 18, fontSize: '0.62rem' }} />}
            </Stack>
            {run.intake.reasoning && (
              <Typography variant="caption" sx={{ color: '#cbd5e1', display: 'block', mt: 0.5 }}>
                {run.intake.reasoning}
              </Typography>
            )}
          </Paper>
        )}

        {/* The A2A chain */}
        {run.answer?.direct ? (
          <Alert severity="info" sx={{ fontSize: '0.82rem' }}>
            Answered at intake — no agents were combined, because none were
            needed. A pipeline of zero.
          </Alert>
        ) : stages.length === 0 ? (
          <Alert severity="info">No stages were recorded for this run.</Alert>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {stages.map((stage, i) => (
              <React.Fragment key={stage.step || i}>
                <AgentNode stage={stage} index={i}
                           isEntry={i === 0} isExit={i === stages.length - 1} />
                {i < stages.length - 1 && (
                  <Stack alignItems="center" sx={{ py: 0.75 }}>
                    <SouthIcon sx={{ fontSize: 16, color: '#475569' }} />
                    <Chip size="small" variant="outlined" label="A2A · result → prompt"
                          sx={{ height: 18, fontSize: '0.58rem', color: '#7dd3fc',
                                borderColor: 'rgba(125,211,252,0.3)' }} />
                  </Stack>
                )}
              </React.Fragment>
            ))}
          </Box>
        )}

        {/* Stages nobody could staff */}
        {(run.unmatched || []).length > 0 && (
          <Alert severity="warning" sx={{ mt: 2, fontSize: '0.78rem' }}>
            {run.unmatched.length} stage{run.unmatched.length === 1 ? '' : 's'} had no
            agent and {run.unmatched.length === 1 ? 'was' : 'were'} left out:
            {' '}{run.unmatched.map((s) => s.need).join('; ')}
          </Alert>
        )}
      </DialogContent>

      {/* Catalogue the combination as one reusable agent */}
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
        {catalogable ? (
          <>
            <Button variant="contained" startIcon={<BookmarkAddIcon />}
                    onClick={() => onCatalogue?.(run)}>
              Save this combination as an agent
            </Button>
            <Typography variant="caption" sx={{ color: '#64748b', flex: 1, minWidth: 180 }}>
              A pipeline of agents is a pipeline of one. Catalogued, it becomes a
              single agent you can drop into the next, larger deal.
            </Typography>
          </>
        ) : (
          <Typography variant="caption" sx={{ color: '#64748b' }}>
            A finished, multi-agent run can be catalogued as a reusable agent.
          </Typography>
        )}
      </Box>
    </Dialog>
  );
}
