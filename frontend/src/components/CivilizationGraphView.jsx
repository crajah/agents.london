import React, { useEffect, useRef } from 'react';
import { Box, Paper, Typography, Button, Chip, Stack } from '@mui/material';
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong';
import AddIcon from '@mui/icons-material/Add';

export default function CivilizationGraphView({ state, onOpenMaterialize }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let animationFrameId;

    const resize = () => {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight || 450;
    };
    resize();
    window.addEventListener('resize', resize);

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const cx = canvas.width / 2;
      const cy = canvas.height / 2;

      const nodes = [
        { id: 'genesis', label: 'GenesisRoot', color: '#ec4899', x: cx, y: cy - 120 },
        { id: 'conductor', label: 'ConductorAgent', color: '#3b82f6', x: cx - 160, y: cy - 10 },
        { id: 'react', label: 'ReActAgent', color: '#10b981', x: cx + 160, y: cy - 10 },
        { id: 'creator', label: 'AgentCreator', color: '#8b5cf6', x: cx - 90, y: cy + 110 },
        { id: 'inspector', label: 'InspectorAgent', color: '#f59e0b', x: cx + 90, y: cy + 110 }
      ];

      // Draw Connection Edges
      ctx.strokeStyle = 'rgba(100, 116, 139, 0.4)';
      ctx.lineWidth = 2;
      nodes.forEach(n => {
        if (n.id !== 'genesis') {
          ctx.beginPath();
          ctx.moveTo(cx, cy - 120);
          ctx.lineTo(n.x, n.y);
          ctx.stroke();
        }
      });

      // Draw Nodes
      nodes.forEach(n => {
        // Node Glow
        ctx.beginPath();
        ctx.arc(n.x, n.y, 28, 0, Math.PI * 2);
        ctx.fillStyle = n.color + '33';
        ctx.fill();

        // Node Solid Inner
        ctx.beginPath();
        ctx.arc(n.x, n.y, 20, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Label
        ctx.fillStyle = '#ffffff';
        ctx.font = '600 12px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(n.label, n.x, n.y + 36);
      });

      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationFrameId);
    };
  }, [state.projectId]);

  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Agent Civilization Universe Graph
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Live topological map of permanent governing agents, Conductor, ReAct, and Kagent worker nodes.
          </Typography>
        </Box>

        <Stack direction="row" spacing={1.5}>
          <Button variant="contained" color="primary" startIcon={<AddIcon />} onClick={onOpenMaterialize}>
            Materialize Agent
          </Button>
        </Stack>
      </Box>

      {/* Canvas Container */}
      <Paper sx={{ p: 2, position: 'relative', height: 420, overflow: 'hidden' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
      </Paper>

      {/* Live Stream Event Log */}
      <Paper sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
          ⚡ Live Inter-Agent Redis Communication Stream
        </Typography>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, maxHeight: 180, overflowY: 'auto', p: 1, backgroundColor: 'rgba(9, 13, 22, 0.7)', borderRadius: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontSize: '0.8rem' }}>
            <Typography variant="caption" color="text.secondary">20:45:10</Typography>
            <Chip label="CONDUCTOR" size="small" color="primary" sx={{ height: 18, fontSize: '0.65rem' }} />
            <Typography variant="body2" sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: '0.8rem' }}>
              ConductorAgent indexed Agent Registry metadata in post-graph-rag for organic discovery.
            </Typography>
          </Box>
        </Box>
      </Paper>
    </Box>
  );
}
