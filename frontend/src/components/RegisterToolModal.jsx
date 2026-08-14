import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, FormControl, InputLabel, Select, MenuItem
} from '@mui/material';

export default function RegisterToolModal({ open, onClose, onRegisterTool }) {
  const [toolId, setToolId] = useState('');
  const [name, setName] = useState('');
  const [scope, setScope] = useState('org');
  const [endpointUrl, setEndpointUrl] = useState('http://localhost:8002/tools/');
  const [schema, setSchema] = useState('{"payload": "str"}');

  const handleSubmit = () => {
    if (!toolId.trim() || !name.trim()) return;

    let parsedSchema = { payload: "str" };
    try {
      parsedSchema = JSON.parse(schema);
    } catch {
      console.log('Invalid JSON schema, using default.');
    }

    onRegisterTool({
      tool_id: toolId.trim().toLowerCase().startsWith('mcp-') ? toolId.trim() : `mcp-${toolId.trim()}`,
      name: name.trim(),
      scope_type: scope,
      endpoint_url: endpointUrl.trim(),
      input_schema: parsedSchema
    });

    setToolId('');
    setName('');
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontWeight: 700 }}>
        🛠️ Register New MCP Tool
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <TextField
          label="Tool ID (e.g. mcp-sql-query)"
          size="small"
          fullWidth
          value={toolId}
          onChange={(e) => setToolId(e.target.value)}
        />

        <TextField
          label="Tool Display Name"
          size="small"
          fullWidth
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <FormControl size="small" fullWidth>
          <InputLabel>Tool Scope</InputLabel>
          <Select
            value={scope}
            label="Tool Scope"
            onChange={(e) => setScope(e.target.value)}
          >
            <MenuItem value="org">Organization Realm (org)</MenuItem>
            <MenuItem value="project">Project Realm (project)</MenuItem>
          </Select>
        </FormControl>

        <TextField
          label="MCP Endpoint URL"
          size="small"
          fullWidth
          value={endpointUrl}
          onChange={(e) => setEndpointUrl(e.target.value)}
        />

        <TextField
          label="Input Schema (JSON)"
          size="small"
          fullWidth
          multiline
          rows={3}
          value={schema}
          onChange={(e) => setSchema(e.target.value)}
        />
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" color="primary">
          Register MCP Tool
        </Button>
      </DialogActions>
    </Dialog>
  );
}
