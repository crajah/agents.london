import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api, attempt } from '../utils/api';
import { Box, Paper, Typography, TextField, Button, Chip, Stack, CircularProgress, Divider } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import HubIcon from '@mui/icons-material/Hub';

const TYPE_COLORS = {
  person: '#ec4899', organization: '#8b5cf6', concept: '#3b82f6', document: '#10b981',
  event: '#f59e0b', location: '#06b6d4', tool: '#f97316', agent: '#a78bfa',
  default: '#64748b'
};

function getColor(type) {
  return TYPE_COLORS[(type || '').toLowerCase()] || TYPE_COLORS.default;
}

export default function GraphRAGExplorer({ projectId, orgId, spaceName }) {
  const canvasRef = useRef(null);
  const [allNodes, setAllNodes] = useState([]);    // accumulated across expansions
  const [allEdges, setAllEdges] = useState([]);
  const [chunks, setChunks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [simNodes, setSimNodes] = useState([]);
  const dragRef = useRef(null);
  // The cursor has to be state, not the ref: changing a ref does not
  // re-render, so reading it during render showed whichever value happened
  // to be current at the last unrelated render.
  const [dragging, setDragging] = useState(false);
  const animRef = useRef(null);

  // Fetch a subgraph centered on a query and merge into existing graph
  const expandGraph = useCallback(async (q) => {
    if (!q.trim()) return;
    setLoading(true);
    try {
      const graphParams = { query: q, depth: 1 };
      if (spaceName && spaceName !== 'all') graphParams.space_name = spaceName;
      const { data, error } = await attempt(
        api.get(`/api/projects/${projectId}/rag/graph`, { params: graphParams }));
      if (!error) {
        const newNodes = data.nodes || [];
        const newEdges = data.edges || [];

        // Merge nodes (deduplicate by id)
        setAllNodes(prev => {
          const existing = new Set(prev.map(n => n.id));
          const merged = [...prev];
          for (const n of newNodes) {
            if (!existing.has(n.id)) {
              existing.add(n.id);
              merged.push(n);
            }
          }
          return merged;
        });

        // Merge edges (deduplicate by source+target+type)
        setAllEdges(prev => {
          const existing = new Set(prev.map(e => `${e.source}|${e.target}|${e.type}`));
          const merged = [...prev];
          for (const e of newEdges) {
            const key = `${e.source}|${e.target}|${e.type}`;
            if (!existing.has(key)) {
              existing.add(key);
              merged.push(e);
            }
          }
          return merged;
        });

        setChunks(data.chunks || []);
      }
    } catch (e) {
      console.error('Graph fetch error:', e);
    } finally {
      setLoading(false);
    }
  }, [projectId, spaceName]);

  const handleSearch = () => {
    if (query.trim()) {
      setAllNodes([]);
      setAllEdges([]);
      setSimNodes([]);
      setSelectedNode(null);
      setSelectedEdge(null);
      expandGraph(query);
    }
  };

  // When a node is double-clicked, expand its connections
  const handleNodeExpand = useCallback((node) => {
    expandGraph(node.id);
  }, [expandGraph]);

  // Position new nodes near their connected neighbors or in a ring
  useEffect(() => {
    if (allNodes.length === 0) { setSimNodes([]); return; }
    const W = canvasRef.current?.parentElement?.clientWidth || 800;
    const H = 500;
    const cx = W / 2, cy = H / 2;

    setSimNodes(prev => {
      const existing = {};
      prev.forEach(n => { existing[n.id] = n; });

      return allNodes.map((n, i) => {
        if (existing[n.id]) return existing[n.id]; // keep existing position
        // Place new nodes near a connected existing node, or in a ring
        const connectedTo = allEdges.find(e => e.source === n.id || e.target === n.id);
        const neighbor = connectedTo && existing[connectedTo.source === n.id ? connectedTo.target : connectedTo.source];
        const bx = neighbor ? neighbor.x : cx;
        const by = neighbor ? neighbor.y : cy;
        const angle = Math.random() * Math.PI * 2;
        const r = 60 + Math.random() * 40;
        return { ...n, x: bx + Math.cos(angle) * r, y: by + Math.sin(angle) * r, vx: 0, vy: 0 };
      });
    });
  }, [allNodes, allEdges]);

  // Force-directed simulation + canvas rendering
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || simNodes.length === 0) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width = canvas.parentElement.clientWidth;
    const H = canvas.height = Math.max(500, canvas.parentElement.clientHeight - 60);

    const nodeMap = {};
    simNodes.forEach(n => { nodeMap[n.id] = n; });

    let frame = 0;
    function simulate() {
      for (let i = 0; i < simNodes.length; i++) {
        for (let j = i + 1; j < simNodes.length; j++) {
          const a = simNodes[i], b = simNodes[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
          const force = 600 / (dist * dist);
          dx /= dist; dy /= dist;
          a.vx -= dx * force; a.vy -= dy * force;
          b.vx += dx * force; b.vy += dy * force;
        }
      }
      for (const e of allEdges) {
        const a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b) continue;
        let dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const force = (dist - 120) * 0.01;
        dx /= dist; dy /= dist;
        a.vx += dx * force; a.vy += dy * force;
        b.vx -= dx * force; b.vy -= dy * force;
      }
      for (const n of simNodes) {
        n.vx += (W / 2 - n.x) * 0.0005;
        n.vy += (H / 2 - n.y) * 0.0005;
        n.vx *= 0.92; n.vy *= 0.92;
        if (dragRef.current?.id !== n.id) {
          n.x += n.vx; n.y += n.vy;
        }
        n.x = Math.max(20, Math.min(W - 20, n.x));
        n.y = Math.max(20, Math.min(H - 20, n.y));
      }

      ctx.clearRect(0, 0, W, H);

      // Edges
      for (const e of allEdges) {
        const a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b) continue;
        const isSel = selectedEdge && selectedEdge.source === e.source && selectedEdge.target === e.target;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = isSel ? '#60a5fa' : 'rgba(148,163,184,0.25)';
        ctx.lineWidth = isSel ? 2.5 : 1;
        ctx.stroke();
        if (e.type) {
          ctx.font = '9px Inter, sans-serif';
          ctx.fillStyle = isSel ? '#93c5fd' : 'rgba(148,163,184,0.4)';
          ctx.textAlign = 'center';
          ctx.fillText(e.type, (a.x + b.x) / 2, (a.y + b.y) / 2 - 4);
        }
      }

      // Nodes
      for (const n of simNodes) {
        const isSel = selectedNode?.id === n.id;
        const radius = isSel ? 10 : 7;
        const color = getColor(n.type);
        if (isSel) {
          ctx.beginPath(); ctx.arc(n.x, n.y, 18, 0, Math.PI * 2);
          ctx.fillStyle = color + '33'; ctx.fill();
        }
        ctx.beginPath(); ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill();
        ctx.strokeStyle = isSel ? '#fff' : 'rgba(255,255,255,0.3)';
        ctx.lineWidth = isSel ? 2 : 1; ctx.stroke();

        ctx.font = `${isSel ? 'bold 11px' : '10px'} Inter, sans-serif`;
        ctx.fillStyle = '#e2e8f0'; ctx.textAlign = 'center';
        ctx.fillText(n.id.length > 22 ? n.id.slice(0, 20) + '..' : n.id, n.x, n.y + radius + 14);
      }

      frame++;
      if (frame < 400) animRef.current = requestAnimationFrame(simulate);
    }
    animRef.current = requestAnimationFrame(simulate);
    return () => cancelAnimationFrame(animRef.current);
  }, [simNodes, allEdges, selectedNode, selectedEdge]);

  // Click: select node/edge. Double-click: expand node connections.
  const lastClickRef = useRef(0);
  const handleCanvasClick = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const now = Date.now();
    const isDouble = now - lastClickRef.current < 350;
    lastClickRef.current = now;

    const nodeMap = {};
    simNodes.forEach(n => { nodeMap[n.id] = n; });

    for (const n of simNodes) {
      if ((mx - n.x) ** 2 + (my - n.y) ** 2 < 200) {
        setSelectedNode(n); setSelectedEdge(null);
        if (isDouble) handleNodeExpand(n);
        return;
      }
    }
    for (const ed of allEdges) {
      const a = nodeMap[ed.source], b = nodeMap[ed.target];
      if (!a || !b) continue;
      const emx = (a.x + b.x) / 2, emy = (a.y + b.y) / 2;
      if ((mx - emx) ** 2 + (my - emy) ** 2 < 400) {
        setSelectedEdge(ed); setSelectedNode(null); return;
      }
    }
    setSelectedNode(null); setSelectedEdge(null);
  }, [simNodes, allEdges, handleNodeExpand]);

  const handleMouseDown = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    for (const n of simNodes) {
      if ((mx - n.x) ** 2 + (my - n.y) ** 2 < 200) { dragRef.current = n; setDragging(true); return; }
    }
  }, [simNodes]);

  const handleMouseMove = useCallback((e) => {
    if (!dragRef.current || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    dragRef.current.x = e.clientX - rect.left;
    dragRef.current.y = e.clientY - rect.top;
  }, []);

  const handleMouseUp = useCallback(() => {
    dragRef.current = null;
    setDragging(false);
  }, []);

  const connectedEdges = selectedNode
    ? allEdges.filter(e => e.source === selectedNode.id || e.target === selectedNode.id)
    : [];

  return (
    <Box sx={{ display: 'flex', gap: 2, height: '100%', minHeight: 550 }}>
      {/* Graph Canvas */}
      <Paper sx={{ flex: 1, p: 0, overflow: 'hidden', position: 'relative', backgroundColor: '#0b0f19', borderRadius: 3 }}>
        {/* Search bar */}
        <Box sx={{ position: 'absolute', top: 12, left: 12, right: 12, zIndex: 2, display: 'flex', gap: 1 }}>
          <TextField size="small" placeholder="Search to find starting nodes..."
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            sx={{ flex: 1, '& .MuiOutlinedInput-root': { backgroundColor: 'rgba(15,23,42,0.9)', fontSize: '0.85rem' } }}
          />
          <Button variant="contained" size="small" onClick={handleSearch} disabled={loading} sx={{ minWidth: 40 }}>
            {loading ? <CircularProgress size={18} /> : <SearchIcon fontSize="small" />}
          </Button>
        </Box>

        {/* Hint */}
        {allNodes.length > 0 && (
          <Box sx={{ position: 'absolute', bottom: 12, left: 12, zIndex: 2 }}>
            <Chip label="Double-click a node to expand its connections" size="small"
              sx={{ fontSize: '0.65rem', height: 20, backgroundColor: 'rgba(15,23,42,0.8)', color: '#94a3b8' }} />
          </Box>
        )}

        {allNodes.length === 0 && !loading ? (
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: 1 }}>
            <HubIcon sx={{ fontSize: 48, color: '#334155' }} />
            <Typography color="text.secondary" variant="body2">Search for an entity to start exploring the knowledge graph.</Typography>
          </Box>
        ) : (
          <canvas ref={canvasRef} onClick={handleCanvasClick}
            onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}
            style={{ width: '100%', height: '100%', cursor: dragging ? 'grabbing' : 'grab' }}
          />
        )}
      </Paper>

      {/* Detail Panel */}
      <Paper sx={{ width: 280, p: 2, display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto', borderRadius: 3 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#a78bfa' }}>
          <HubIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'text-bottom' }} /> Graph Explorer
        </Typography>
        <Stack spacing={0.5}>
          <Typography variant="caption" color="text.secondary">Nodes: {allNodes.length}</Typography>
          <Typography variant="caption" color="text.secondary">Edges: {allEdges.length}</Typography>
        </Stack>
        <Divider />

        {selectedNode ? (
          <Box>
            <Chip label={selectedNode.type || 'entity'} size="small"
              sx={{ mb: 1, backgroundColor: getColor(selectedNode.type) + '33', color: getColor(selectedNode.type) }} />
            <Typography variant="subtitle2" sx={{ fontWeight: 700, wordBreak: 'break-word' }}>{selectedNode.id}</Typography>
            {selectedNode.description && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1, fontSize: '0.8rem' }}>{selectedNode.description}</Typography>
            )}
            <Button size="small" variant="outlined" sx={{ mt: 1, fontSize: '0.7rem' }}
              onClick={() => handleNodeExpand(selectedNode)} disabled={loading}>
              Expand Connections
            </Button>
            {connectedEdges.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>Connections ({connectedEdges.length})</Typography>
                {connectedEdges.map((ce, i) => (
                  <Box key={i} sx={{ mt: 0.5, p: 1, borderRadius: 1, backgroundColor: 'rgba(255,255,255,0.03)', cursor: 'pointer' }}
                    onClick={() => setSelectedEdge(ce)}>
                    <Typography variant="caption" sx={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                      {ce.source === selectedNode.id ? ce.target : ce.source}
                      <Chip label={ce.type} size="small" sx={{ ml: 0.5, height: 16, fontSize: '0.6rem' }} />
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        ) : selectedEdge ? (
          <Box>
            <Typography variant="caption" color="text.secondary">Relationship</Typography>
            <Chip label={selectedEdge.type || 'related'} size="small" sx={{ mt: 0.5, mb: 1 }} />
            <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
              <strong>{selectedEdge.source}</strong> &rarr; <strong>{selectedEdge.target}</strong>
            </Typography>
            {selectedEdge.description && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1, fontSize: '0.8rem' }}>{selectedEdge.description}</Typography>
            )}
          </Box>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.8rem' }}>
            Search to find starting nodes. Click to select, double-click to expand connections. Drag to rearrange.
          </Typography>
        )}

        {chunks.length > 0 && (
          <>
            <Divider />
            <Typography variant="caption" sx={{ fontWeight: 600 }}>Source Chunks</Typography>
            <Box sx={{ maxHeight: 200, overflowY: 'auto' }}>
              {chunks.slice(0, 5).map((c, i) => (
                <Paper key={i} elevation={0} sx={{ p: 1, mb: 0.5, backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: 1 }}>
                  <Typography variant="caption" sx={{ fontSize: '0.7rem', color: '#94a3b8', wordBreak: 'break-word' }}>{c.content}</Typography>
                </Paper>
              ))}
            </Box>
          </>
        )}
      </Paper>
    </Box>
  );
}
