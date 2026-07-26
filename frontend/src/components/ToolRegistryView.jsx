import React from 'react';
import {
  Box, Paper, Typography, Button, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Chip
} from '@mui/material';
import BuildIcon from '@mui/icons-material/Build';
import AddIcon from '@mui/icons-material/Add';

export default function ToolRegistryView({ state }) {
  return (
    <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 3, height: '100%', overflowY: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Model Context Protocol (MCP) Tool Registry
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Registered MCP tools linked to Organization realms or specific Projects.
          </Typography>
        </Box>

        <Button variant="contained" color="primary" startIcon={<AddIcon />}>
          Register MCP Tool
        </Button>
      </Box>

      {/* Table Container */}
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
    </Box>
  );
}
