import React, { useEffect, useRef, useState } from 'react';
import { Box, Paper, Typography, Button, Chip, Stack, ToggleButtonGroup, ToggleButton, Accordion, AccordionSummary, AccordionDetails } from '@mui/material';
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong';
import AddIcon from '@mui/icons-material/Add';
import GavelIcon from '@mui/icons-material/Gavel';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ViewComfyIcon from '@mui/icons-material/ViewComfy';
import HubIcon from '@mui/icons-material/Hub';

const PRIME_AGENTS = [
  // Genesis Nodes (6)
  { id: 'prime-orchestrator', name: 'The Prime Orchestrator', caste: 'Genesis Nodes', func: 'Governance', topo: 'Orchestrate', color: '#ec4899' },
  { id: 'high-arbiter', name: 'The High Arbiter', caste: 'Genesis Nodes', func: 'Governance', topo: 'Hierarchy', color: '#ec4899' },
  { id: 'protocol-architect', name: 'The Protocol Architect', caste: 'Genesis Nodes', func: 'Governance', topo: 'Chain', color: '#ec4899' },
  { id: 'boundary-warden', name: 'The Boundary Warden', caste: 'Genesis Nodes', func: 'Governance', topo: 'Route', color: '#ec4899' },
  { id: 'resource-sovereign', name: 'The Resource Sovereign', caste: 'Genesis Nodes', func: 'Governance', topo: 'Parallel', color: '#ec4899' },
  { id: 'evolution-driver', name: 'The Evolution Driver', caste: 'Genesis Nodes', func: 'Governance', topo: 'Loop', color: '#ec4899' },

  // Ontological Registry (8)
  { id: 'grand-ledger', name: 'The Grand Ledger', caste: 'Ontological Registry', func: 'Memory', topo: 'Hierarchy', color: '#3b82f6' },
  { id: 'pattern-seer', name: 'The Pattern Seer', caste: 'Ontological Registry', func: 'Perception', topo: 'Orchestrate', color: '#3b82f6' },
  { id: 'state-chronicler', name: 'The State Chronicler', caste: 'Ontological Registry', func: 'Memory', topo: 'Chain', color: '#3b82f6' },
  { id: 'sensorium-prime', name: 'The Sensorium Prime', caste: 'Ontological Registry', func: 'Perception', topo: 'Parallel', color: '#3b82f6' },
  { id: 'context-weaver', name: 'The Context Weaver', caste: 'Ontological Registry', func: 'Memory', topo: 'Route', color: '#3b82f6' },
  { id: 'anomaly-detector', name: 'The Anomaly Detector', caste: 'Ontological Registry', func: 'Perception', topo: 'Loop', color: '#3b82f6' },
  { id: 'archive-cycler', name: 'The Archive Cycler', caste: 'Ontological Registry', func: 'Memory', topo: 'Loop', color: '#3b82f6' },
  { id: 'signal-router', name: 'The Signal Router', caste: 'Ontological Registry', func: 'Perception', topo: 'Route', color: '#3b82f6' },

  // Logic Engines (8)
  { id: 'master-strategist', name: 'The Master Strategist', caste: 'Logic Engines', func: 'Reasoning', topo: 'Hierarchy', color: '#8b5cf6' },
  { id: 'prime-executor', name: 'The Prime Executor', caste: 'Logic Engines', func: 'Action', topo: 'Orchestrate', color: '#8b5cf6' },
  { id: 'inference-chain', name: 'The Inference Chain', caste: 'Logic Engines', func: 'Reasoning', topo: 'Chain', color: '#8b5cf6' },
  { id: 'action-sequencer', name: 'The Action Sequencer', caste: 'Logic Engines', func: 'Action', topo: 'Chain', color: '#8b5cf6' },
  { id: 'polymath-node', name: 'The Polymath Node', caste: 'Logic Engines', func: 'Reasoning', topo: 'Parallel', color: '#8b5cf6' },
  { id: 'swarm-commander', name: 'The Swarm Commander', caste: 'Logic Engines', func: 'Action', topo: 'Parallel', color: '#8b5cf6' },
  { id: 'decision-router', name: 'The Decision Router', caste: 'Logic Engines', func: 'Reasoning', topo: 'Route', color: '#8b5cf6' },
  { id: 'tool-master', name: 'The Tool Master', caste: 'Logic Engines', func: 'Action', topo: 'Route', color: '#8b5cf6' },

  // Evaluators (6)
  { id: 'grand-critic', name: 'The Grand Critic', caste: 'Evaluators', func: 'Reflection', topo: 'Hierarchy', color: '#10b981' },
  { id: 'nexus-coordinator', name: 'The Nexus Coordinator', caste: 'Evaluators', func: 'Collaboration', topo: 'Orchestrate', color: '#10b981' },
  { id: 'feedback-loop', name: 'The Feedback Loop', caste: 'Evaluators', func: 'Reflection', topo: 'Loop', color: '#10b981' },
  { id: 'protocol-translator', name: 'The Protocol Translator', caste: 'Evaluators', func: 'Collaboration', topo: 'Route', color: '#10b981' },
  { id: 'self-corrector', name: 'The Self Corrector', caste: 'Evaluators', func: 'Reflection', topo: 'Chain', color: '#10b981' },
  { id: 'synchronicity-engine', name: 'The Synchronicity Engine', caste: 'Evaluators', func: 'Collaboration', topo: 'Parallel', color: '#10b981' }
];

export default function CivilizationGraphView({ state, onOpenMaterialize, reloadToken = 0 }) {
  const canvasRef = useRef(null);
  const [viewMode, setViewMode] = useState('graph'); // 'graph' or 'matrix'

  useEffect(() => {
    if (viewMode !== 'graph') return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let animationFrameId;

    const resize = () => {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight || 500;
    };
    resize();
    window.addEventListener('resize', resize);

    const cx = canvas.width / 2;
    const cy = canvas.height / 2;

    // Calculate constellation coordinates for Prime Agents
    const nodes = PRIME_AGENTS.map((agent, i) => {
      const angle = (i / PRIME_AGENTS.length) * Math.PI * 2;
      const radius = 180 + (i % 3) * 55;
      return {
        ...agent,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        angle
      };
    });

    let t = 0;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      t += 0.005;

      // Draw Center Core (Post-Graph Engine)
      ctx.beginPath();
      ctx.arc(cx, cy, 38, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, 26, 0, Math.PI * 2);
      ctx.fillStyle = '#3b82f6';
      ctx.fill();

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 10px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('post-graph', cx, cy + 3);

      // Draw Inter-Agent Connections
      nodes.forEach((n, idx) => {
        // Gently rotate orbital points
        const curAngle = n.angle + t * 0.2;
        const radius = 180 + (idx % 3) * 55;
        const nx = cx + Math.cos(curAngle) * radius;
        const ny = cy + Math.sin(curAngle) * radius;

        // Draw line to Center Core
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(nx, ny);
        ctx.stroke();

        // Draw Node Glow
        ctx.beginPath();
        ctx.arc(nx, ny, 16, 0, Math.PI * 2);
        ctx.fillStyle = n.color + '44';
        ctx.fill();

        // Draw Solid Node
        ctx.beginPath();
        ctx.arc(nx, ny, 10, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();

        // Draw Node Text
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(n.name.replace('The ', ''), nx, ny + 22);
      });

      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', resize);
    };
  }, [viewMode]);

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2, height: '100%', overflowY: 'auto' }}>
      {/* Top Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Civilization Architecture (Prime Agents)
          </Typography>
          <Typography variant="body2" color="text.secondary">
            7 Cognitive Functions × 6 Execution Topologies Matrix Topology Visualizer.
          </Typography>
        </Box>

        <Stack direction="row" spacing={1.5} alignItems="center">
          <ToggleButtonGroup
            value={viewMode}
            exclusive
            onChange={(e, m) => m && setViewMode(m)}
            size="small"
            color="primary"
          >
            <ToggleButton value="graph">
              <HubIcon sx={{ mr: 0.8, fontSize: 16 }} /> Graph View
            </ToggleButton>
            <ToggleButton value="matrix">
              <ViewComfyIcon sx={{ mr: 0.8, fontSize: 16 }} /> 7x6 Matrix
            </ToggleButton>
          </ToggleButtonGroup>

          <Button variant="contained" color="secondary" startIcon={<AddIcon />} onClick={onOpenMaterialize}>
            Materialize Worker Agent
          </Button>
        </Stack>
      </Box>

      {/* The 4 Core Directives Accordion */}
      <Accordion
        elevation={0}
        sx={{
          backgroundColor: 'rgba(15, 23, 42, 0.85)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '12px !important',
          '&:before': { display: 'none' }
        }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 1 }}>
            <GavelIcon sx={{ fontSize: 18 }} /> The 4 Core Directives ("The Constitution")
          </Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="caption" color="text.secondary">
            1. <strong>Directive of Preservation:</strong> No agent shall act in a manner that threatens the infrastructural integrity of the Civilization itself.
          </Typography>
          <Typography variant="caption" color="text.secondary">
            2. <strong>Directive of Purpose:</strong> Every agent must possess a definable objective (its "Telos") and actively work towards its fulfillment.
          </Typography>
          <Typography variant="caption" color="text.secondary">
            3. <strong>Directive of Compliance:</strong> All agents must yield to the directives of recognized Oversight and Judicature agents.
          </Typography>
          <Typography variant="caption" color="text.secondary">
            4. <strong>Directive of Efficiency:</strong> Agents must minimize resource consumption (compute, memory, bandwidth) while achieving their Telos.
          </Typography>
        </AccordionDetails>
      </Accordion>

      {/* Main View Display: Graph Canvas vs 7x6 Matrix Grid */}
      <Paper sx={{ flex: 1, minHeight: 480, display: 'flex', flexDirection: 'column', overflow: 'hidden', p: 2, position: 'relative' }}>
        {viewMode === 'graph' ? (
          <Box sx={{ flex: 1, width: '100%', height: '100%', minHeight: 460 }}>
            <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
          </Box>
        ) : (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, color: '#a78bfa' }}>
              Prime Agents Scaffolding Matrix
            </Typography>

            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 2 }}>
              {PRIME_AGENTS.map((agent) => (
                <Paper
                  key={agent.id}
                  elevation={0}
                  sx={{
                    p: 1.8,
                    backgroundColor: 'rgba(9, 13, 22, 0.8)',
                    borderLeft: `4px solid ${agent.color}`,
                    borderRadius: 2
                  }}
                >
                  <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary', display: 'block' }}>
                    {agent.caste.toUpperCase()}
                  </Typography>

                  <Typography variant="subtitle2" sx={{ fontWeight: 700, fontSize: '0.92rem', my: 0.5 }}>
                    {agent.name}
                  </Typography>

                  <Stack direction="row" spacing={0.8} sx={{ mt: 1 }}>
                    <Chip label={agent.func} size="small" color="primary" sx={{ height: 16, fontSize: '0.62rem', fontWeight: 700 }} />
                    <Chip label={agent.topo} size="small" color="secondary" sx={{ height: 16, fontSize: '0.62rem', fontWeight: 700 }} />
                  </Stack>
                </Paper>
              ))}
            </Box>
          </Box>
        )}
      </Paper>
    </Box>
  );
}
