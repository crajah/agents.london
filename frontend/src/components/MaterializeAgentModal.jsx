import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, FormControl, InputLabel, Select, MenuItem, Box
} from '@mui/material';

export default function MaterializeAgentModal({ open, onClose, state, onSubmit }) {
  const [name, setName] = useState('');
  const [parent, setParent] = useState(`creator-${state.projectId}`);
  const [prompt, setPrompt] = useState('');
  const [tools, setTools] = useState('mcp-pgvector-search, mcp-redis-queue');

  const handleSubmit = () => {
    onSubmit({
      name: name || 'CustomWorker',
      parentId: parent,
      systemPrompt: prompt || 'Specialized worker agent',
      tools: tools.split(',').map(t => t.trim())
    });
    setName('');
    setPrompt('');
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700 }}>
        Materialize New Progeny Worker Agent
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <TextField
          label="Agent Name"
          size="small"
          fullWidth
          placeholder="e.g. DataSynthesizerWorker"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <FormControl size="small" fullWidth>
          <InputLabel>Parent Agent (Progeny Origin)</InputLabel>
          <Select
            value={parent}
            label="Parent Agent (Progeny Origin)"
            onChange={(e) => setParent(e.target.value)}
          >
            <MenuItem value={`creator-${state.projectId}`}>AgentCreator-{state.projectId}</MenuItem>
            <MenuItem value={`conductor-${state.projectId}`}>ConductorAgent-{state.projectId}</MenuItem>
            <MenuItem value={`react-${state.projectId}`}>ReActAgent-{state.projectId}</MenuItem>
          </Select>
        </FormControl>

        <TextField
          label="System Prompt"
          size="small"
          fullWidth
          multiline
          rows={3}
          placeholder="You are a specialized worker agent responsible for processing raw payloads..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <TextField
          label="Attach MCP Tools (comma-separated)"
          size="small"
          fullWidth
          value={tools}
          onChange={(e) => setTools(e.target.value)}
        />
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" color="primary">
          Materialize Agent via Kagent
        </Button>
      </DialogActions>
    </Dialog>
  );
}
