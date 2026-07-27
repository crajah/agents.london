import React, { useState } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  IconButton, Tooltip, Chip, Stack, Button, Divider, ToggleButtonGroup, ToggleButton
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import CodeIcon from '@mui/icons-material/Code';
import TableChartIcon from '@mui/icons-material/TableChart';
import DataObjectIcon from '@mui/icons-material/DataObject';
import DescriptionIcon from '@mui/icons-material/Description';
import WebIcon from '@mui/icons-material/Web';
import LaunchIcon from '@mui/icons-material/Launch';

/**
 * HtmlPreviewCard Component
 * Renders HTML output inside an isolated sandboxed iframe with a toggle for live preview vs raw code.
 */
function HtmlPreviewCard({ htmlContent, handleCopy, copied }) {
  const [viewMode, setViewMode] = useState('preview');

  const handleOpenWindow = () => {
    const win = window.open();
    if (win) {
      win.document.write(htmlContent);
      win.document.close();
    }
  };

  return (
    <Paper elevation={0} sx={{ bgcolor: 'rgba(9, 13, 22, 0.95)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: 2, p: 2, my: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Chip label="DETECTED FORMAT: LIVE HTML & WEB UI" size="small" icon={<WebIcon />} color="success" sx={{ height: 22, fontSize: '0.65rem', fontWeight: 700 }} />
          <ToggleButtonGroup
            value={viewMode}
            exclusive
            onChange={(e, val) => val && setViewMode(val)}
            size="small"
            sx={{ height: 24 }}
          >
            <ToggleButton value="preview" sx={{ fontSize: '0.65rem', py: 0, px: 1, color: '#10b981' }}>🖥️ Live Preview</ToggleButton>
            <ToggleButton value="code" sx={{ fontSize: '0.65rem', py: 0, px: 1, color: '#94a3b8' }}>{`<> Source Code`}</ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        <Stack direction="row" spacing={0.5}>
          <Tooltip title="Pop out in New Tab">
            <IconButton size="small" onClick={handleOpenWindow} sx={{ color: '#10b981' }}>
              <LaunchIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={copied ? "Copied!" : "Copy HTML Code"}>
            <IconButton size="small" onClick={() => handleCopy(htmlContent)} sx={{ color: '#10b981' }}>
              {copied ? <CheckIcon fontSize="small" sx={{ color: '#10b981' }} /> : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      {viewMode === 'preview' ? (
        <Box sx={{ width: '100%', height: 380, bgcolor: '#ffffff', borderRadius: 1.5, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)' }}>
          <iframe
            title="HTML Live Render"
            srcDoc={htmlContent}
            sandbox="allow-scripts"
            style={{ width: '100%', height: '100%', border: 'none' }}
          />
        </Box>
      ) : (
        <Box sx={{ overflowX: 'auto', maxHeight: 380 }}>
          <Typography component="pre" variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#10b981', fontSize: '0.8rem', whiteSpace: 'pre-wrap', m: 0 }}>
            {htmlContent}
          </Typography>
        </Box>
      )}
    </Paper>
  );
}

/**
 * Intelligent AutoFormatDetectorRenderer Component
 * Detects LLM output formats (HTML, JSON, Tables, Code Blocks, Markdown, Text)
 * and automatically renders them in optimal visual representations.
 */
export default function AutoFormatDetectorRenderer({ content }) {
  const [copied, setCopied] = useState(false);

  if (!content || typeof content !== 'string') {
    return <Typography variant="body2">{String(content || '')}</Typography>;
  }

  const trimmed = content.trim();

  // Helper for copy to clipboard
  const handleCopy = (textToCopy) => {
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // -------------------------------------------------------------------------
  // 1. HTML DETECTION & RENDERING (iframe sandbox)
  // -------------------------------------------------------------------------
  const htmlCodeMatch = trimmed.match(/^```(?:html)?\s*([\s\S]*?)\s*```$/i);
  const potentialHtml = htmlCodeMatch ? htmlCodeMatch[1].trim() : trimmed;

  const isHtml =
    potentialHtml.match(/<!DOCTYPE html/i) ||
    potentialHtml.match(/<html[\s>]/i) ||
    potentialHtml.match(/<body[\s>]/i) ||
    (potentialHtml.includes('<div') && potentialHtml.includes('</div>')) ||
    (potentialHtml.includes('<svg') && potentialHtml.includes('</svg>')) ||
    (potentialHtml.includes('<style') && potentialHtml.includes('</style>'));

  if (isHtml) {
    return <HtmlPreviewCard htmlContent={potentialHtml} handleCopy={handleCopy} copied={copied} />;
  }

  // -------------------------------------------------------------------------
  // 2. JSON DETECTION & RENDERING
  // -------------------------------------------------------------------------
  let jsonObject = null;
  let jsonString = '';

  const jsonCodeMatch = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  const potentialJson = jsonCodeMatch ? jsonCodeMatch[1].trim() : trimmed;

  if ((potentialJson.startsWith('{') && potentialJson.endsWith('}')) || (potentialJson.startsWith('[') && potentialJson.endsWith(']'))) {
    try {
      jsonObject = JSON.parse(potentialJson);
      jsonString = JSON.stringify(jsonObject, null, 2);
    } catch (e) {
      jsonObject = null;
    }
  }

  if (jsonObject !== null) {
    return (
      <Paper elevation={0} sx={{ bgcolor: 'rgba(9, 13, 22, 0.95)', border: '1px solid rgba(56, 189, 248, 0.2)', borderRadius: 2, p: 2, my: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
          <Chip label="DETECTED FORMAT: JSON OBJECT" size="small" icon={<DataObjectIcon />} color="primary" sx={{ height: 22, fontSize: '0.65rem', fontWeight: 700 }} />
          <Tooltip title={copied ? "Copied!" : "Copy JSON"}>
            <IconButton size="small" onClick={() => handleCopy(jsonString)} sx={{ color: '#38bdf8' }}>
              {copied ? <CheckIcon fontSize="small" sx={{ color: '#10b981' }} /> : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>
        <Box sx={{ overflowX: 'auto', maxHeight: 400 }}>
          <Typography component="pre" variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#38bdf8', fontSize: '0.8rem', whiteSpace: 'pre-wrap', m: 0 }}>
            {jsonString}
          </Typography>
        </Box>
      </Paper>
    );
  }

  // -------------------------------------------------------------------------
  // 3. MARKDOWN / PIPE TABLE DETECTION & RENDERING
  // -------------------------------------------------------------------------
  const lines = trimmed.split('\n');
  const tableLines = lines.filter(l => l.trim().startsWith('|') && l.trim().endsWith('|'));
  
  if (tableLines.length >= 2) {
    const rawHeaders = tableLines[0].split('|').map(s => s.trim()).filter(Boolean);
    const dataRows = tableLines.slice(2).map(rowStr => rowStr.split('|').map(s => s.trim()).filter(Boolean));

    if (rawHeaders.length > 0 && dataRows.length > 0) {
      return (
        <Paper elevation={0} sx={{ bgcolor: 'rgba(15, 23, 42, 0.75)', border: '1px solid rgba(129, 140, 248, 0.2)', borderRadius: 2, p: 2, my: 1 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Chip label={`DETECTED FORMAT: DATA TABLE (${dataRows.length} ROWS)`} size="small" icon={<TableChartIcon />} color="secondary" sx={{ height: 22, fontSize: '0.65rem', fontWeight: 700 }} />
            <Tooltip title={copied ? "Copied!" : "Copy Table Markdown"}>
              <IconButton size="small" onClick={() => handleCopy(tableLines.join('\n'))} sx={{ color: '#818cf8' }}>
                {copied ? <CheckIcon fontSize="small" sx={{ color: '#10b981' }} /> : <ContentCopyIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
          </Stack>

          <TableContainer sx={{ borderRadius: 1.5, border: '1px solid rgba(255,255,255,0.08)' }}>
            <Table size="small">
              <TableHead sx={{ bgcolor: 'rgba(30, 41, 59, 0.9)' }}>
                <TableRow>
                  {rawHeaders.map((h, i) => (
                    <TableCell key={i} sx={{ color: '#818cf8', fontWeight: 700, fontSize: '0.75rem', py: 1 }}>
                      {h}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {dataRows.map((row, rIdx) => (
                  <TableRow key={rIdx} sx={{ '&:nth-of-type(odd)': { bgcolor: 'rgba(255,255,255,0.02)' } }}>
                    {row.map((cell, cIdx) => (
                      <TableCell key={cIdx} sx={{ color: '#f8fafc', fontSize: '0.78rem', py: 0.8 }}>
                        {cell}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      );
    }
  }

  // -------------------------------------------------------------------------
  // 4. CODE BLOCK DETECTION & RENDERING (python, js, bash, sql, etc.)
  // -------------------------------------------------------------------------
  const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
  const matches = [...trimmed.matchAll(codeBlockRegex)];

  if (matches.length > 0) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, my: 1 }}>
        {matches.map((m, idx) => {
          const lang = (m[1] || 'code').toUpperCase();
          const codeSnippet = m[2];
          return (
            <Paper key={idx} elevation={0} sx={{ bgcolor: 'rgba(9, 13, 22, 0.95)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: 2, p: 2 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Chip label={`DETECTED FORMAT: ${lang} CODE`} size="small" icon={<CodeIcon />} sx={{ height: 20, fontSize: '0.62rem', fontWeight: 700, bgcolor: 'rgba(255,255,255,0.08)', color: '#a78bfa' }} />
                <Tooltip title={copied ? "Copied!" : "Copy Code"}>
                  <IconButton size="small" onClick={() => handleCopy(codeSnippet)} sx={{ color: '#a78bfa' }}>
                    {copied ? <CheckIcon fontSize="small" sx={{ color: '#10b981' }} /> : <ContentCopyIcon fontSize="small" />}
                  </IconButton>
                </Tooltip>
              </Stack>
              <Box sx={{ overflowX: 'auto', maxHeight: 350 }}>
                <Typography component="pre" variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#f1f5f9', fontSize: '0.82rem', whiteSpace: 'pre-wrap', m: 0 }}>
                  {codeSnippet}
                </Typography>
              </Box>
            </Paper>
          );
        })}
      </Box>
    );
  }

  // -------------------------------------------------------------------------
  // 5. STRUCTURED MARKDOWN / TEXT DEFAULT RENDERING
  // -------------------------------------------------------------------------
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography variant="body2" sx={{ fontSize: '0.9rem', lineHeight: 1.6, color: '#f8fafc', whiteSpace: 'pre-wrap' }}>
        {trimmed}
      </Typography>
    </Box>
  );
}
