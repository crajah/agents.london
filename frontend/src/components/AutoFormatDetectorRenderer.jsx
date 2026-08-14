import React, { useState } from 'react';
import {
  Box, Paper, Typography,
  IconButton, Tooltip, Chip, Stack, Divider, ToggleButtonGroup, ToggleButton
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import CodeIcon from '@mui/icons-material/Code';
import DataObjectIcon from '@mui/icons-material/DataObject';
import WebIcon from '@mui/icons-material/Web';
import LaunchIcon from '@mui/icons-material/Launch';

/**
 * HtmlPreviewCard Component
 * Renders standalone HTML documents inside an isolated sandboxed iframe with a toggle for live preview vs raw code.
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
          <Chip label="DETECTED FORMAT: STANDALONE HTML PAGE" size="small" icon={<WebIcon />} color="success" sx={{ height: 22, fontSize: '0.65rem', fontWeight: 700 }} />
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
 * Helper to render inline markdown elements (bold, italic, code)
 */
function renderInlineMarkdown(text) {
  if (!text) return null;

  // Split by inline code blocks `code`
  const codeParts = text.split(/(`[^`]+`)/g);

  return codeParts.map((part, idx) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <Box
          key={idx}
          component="code"
          sx={{
            fontFamily: '"JetBrains Mono", monospace',
            bgcolor: 'rgba(56, 189, 248, 0.15)',
            color: '#38bdf8',
            px: 0.8,
            py: 0.2,
            borderRadius: 1,
            fontSize: '0.85em'
          }}
        >
          {part.slice(1, -1)}
        </Box>
      );
    }

    // Process bold **text**
    const boldParts = part.split(/(\*\*[^*]+\*\*|__[^_]+__)/g);
    return boldParts.map((bPart, bIdx) => {
      if ((bPart.startsWith('**') && bPart.endsWith('**')) || (bPart.startsWith('__') && bPart.endsWith('__'))) {
        return <strong key={`${idx}-${bIdx}`} style={{ color: '#f8fafc', fontWeight: 700 }}>{bPart.slice(2, -2)}</strong>;
      }

      // Process italic *text*
      const italicParts = bPart.split(/(\*[^*]+\*|_[^_]+_)/g);
      return italicParts.map((iPart, iIdx) => {
        if ((iPart.startsWith('*') && iPart.endsWith('*')) || (iPart.startsWith('_') && iPart.endsWith('_'))) {
          return <em key={`${idx}-${bIdx}-${iIdx}`} style={{ color: '#cbd5e1' }}>{iPart.slice(1, -1)}</em>;
        }
        return iPart;
      });
    });
  });
}

/**
 * Intelligent AutoFormatDetectorRenderer Component
 * Detects and renders full Markdown documents, Code blocks, JSON, Pipe Tables, and Standalone HTML.
 */
export default function AutoFormatDetectorRenderer({ content }) {
  const [copied, setCopied] = useState(false);

  if (!content || typeof content !== 'string') {
    return <Typography variant="body2">{String(content || '')}</Typography>;
  }

  const trimmed = content.trim();

  const handleCopy = (textToCopy) => {
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // -------------------------------------------------------------------------
  // 1. STANDALONE FULL HTML PAGE DETECTION
  // -------------------------------------------------------------------------
  const htmlCodeMatch = trimmed.match(/^```(?:html)?\s*([\s\S]*?)\s*```$/i);
  const potentialHtml = htmlCodeMatch ? htmlCodeMatch[1].trim() : trimmed;
  const isFullHtmlPage =
    potentialHtml.match(/^<!DOCTYPE html/i) ||
    potentialHtml.match(/^<html[\s>]/i) ||
    (potentialHtml.includes('<head>') && potentialHtml.includes('<body>'));

  if (isFullHtmlPage) {
    return <HtmlPreviewCard htmlContent={potentialHtml} handleCopy={handleCopy} copied={copied} />;
  }

  // -------------------------------------------------------------------------
  // 2. STANDALONE JSON OBJECT DETECTION
  // -------------------------------------------------------------------------
  let jsonObject = null;
  let jsonString = '';
  const jsonCodeMatch = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  const potentialJson = jsonCodeMatch ? jsonCodeMatch[1].trim() : trimmed;

  if ((potentialJson.startsWith('{') && potentialJson.endsWith('}')) || (potentialJson.startsWith('[') && potentialJson.endsWith(']'))) {
    try {
      jsonObject = JSON.parse(potentialJson);
      jsonString = JSON.stringify(jsonObject, null, 2);
    } catch {
      jsonObject = null;
    }
  }

  if (jsonObject !== null && !trimmed.includes('\n\n#')) {
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
  // 3. FULL MARKDOWN & SEQUENTIAL BLOCK PARSER
  // Parses markdown headers, bullet points, code blocks, tables, and text sequentially
  // -------------------------------------------------------------------------
  const blocks = [];
  const lines = trimmed.split('\n');
  let currentTextBlock = [];
  let inCodeBlock = false;
  let codeBlockLang = '';
  let currentCodeLines = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fenceMatch = line.match(/^```(\w+)?/);

    if (fenceMatch) {
      if (inCodeBlock) {
        // End of code block
        blocks.push({
          type: 'code',
          lang: codeBlockLang || 'code',
          content: currentCodeLines.join('\n')
        });
        currentCodeLines = [];
        inCodeBlock = false;
      } else {
        // Start of code block - flush text block first
        if (currentTextBlock.length > 0) {
          blocks.push({ type: 'text', content: currentTextBlock.join('\n') });
          currentTextBlock = [];
        }
        inCodeBlock = true;
        codeBlockLang = fenceMatch[1] || '';
      }
      continue;
    }

    if (inCodeBlock) {
      currentCodeLines.push(line);
    } else {
      currentTextBlock.push(line);
    }
  }

  if (inCodeBlock && currentCodeLines.length > 0) {
    blocks.push({ type: 'code', lang: codeBlockLang || 'code', content: currentCodeLines.join('\n') });
  } else if (currentTextBlock.length > 0) {
    blocks.push({ type: 'text', content: currentTextBlock.join('\n') });
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {blocks.map((block, bIdx) => {
        if (block.type === 'code') {
          return (
            <Paper key={bIdx} elevation={0} sx={{ bgcolor: 'rgba(9, 13, 22, 0.95)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: 2, p: 2, my: 0.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Chip label={`${(block.lang || 'code').toUpperCase()} CODE`} size="small" icon={<CodeIcon />} sx={{ height: 20, fontSize: '0.62rem', fontWeight: 700, bgcolor: 'rgba(255,255,255,0.08)', color: '#a78bfa' }} />
                <Tooltip title={copied ? "Copied!" : "Copy Code"}>
                  <IconButton size="small" onClick={() => handleCopy(block.content)} sx={{ color: '#a78bfa' }}>
                    {copied ? <CheckIcon fontSize="small" sx={{ color: '#10b981' }} /> : <ContentCopyIcon fontSize="small" />}
                  </IconButton>
                </Tooltip>
              </Stack>
              <Box sx={{ overflowX: 'auto', maxHeight: 350 }}>
                <Typography component="pre" variant="caption" sx={{ fontFamily: '"JetBrains Mono", monospace', color: '#f1f5f9', fontSize: '0.82rem', whiteSpace: 'pre-wrap', m: 0 }}>
                  {block.content}
                </Typography>
              </Box>
            </Paper>
          );
        }

        // Render Text / Markdown Lines
        const textLines = block.content.split('\n');
        return (
          <Box key={bIdx} sx={{ display: 'flex', flexDirection: 'column', gap: 0.8 }}>
            {textLines.map((line, lIdx) => {
              const trimmedLine = line.trim();

              // Headers #, ##, ###, ####
              if (trimmedLine.startsWith('# ')) {
                return (
                  <Typography key={lIdx} variant="h6" sx={{ fontWeight: 800, color: '#38bdf8', mt: 1.5, mb: 0.5, fontSize: '1.15rem' }}>
                    {renderInlineMarkdown(trimmedLine.slice(2))}
                  </Typography>
                );
              }
              if (trimmedLine.startsWith('## ')) {
                return (
                  <Typography key={lIdx} variant="subtitle1" sx={{ fontWeight: 700, color: '#818cf8', mt: 1.2, mb: 0.4, fontSize: '1.02rem' }}>
                    {renderInlineMarkdown(trimmedLine.slice(3))}
                  </Typography>
                );
              }
              if (trimmedLine.startsWith('### ')) {
                return (
                  <Typography key={lIdx} variant="subtitle2" sx={{ fontWeight: 700, color: '#f8fafc', mt: 1, mb: 0.3, fontSize: '0.92rem' }}>
                    {renderInlineMarkdown(trimmedLine.slice(4))}
                  </Typography>
                );
              }
              if (trimmedLine.startsWith('#### ')) {
                return (
                  <Typography key={lIdx} variant="caption" sx={{ fontWeight: 700, color: '#cbd5e1', mt: 0.8, mb: 0.2, fontSize: '0.85rem' }}>
                    {renderInlineMarkdown(trimmedLine.slice(5))}
                  </Typography>
                );
              }

              // Horizontal Divider
              if (trimmedLine === '---' || trimmedLine === '***') {
                return <Divider key={lIdx} sx={{ my: 1, borderColor: 'rgba(255,255,255,0.08)' }} />;
              }

              // Bullet list items
              if (trimmedLine.startsWith('- ') || trimmedLine.startsWith('* ')) {
                return (
                  <Box key={lIdx} sx={{ display: 'flex', gap: 1, pl: 1.5, py: 0.1 }}>
                    <Typography variant="body2" sx={{ color: '#38bdf8', fontWeight: 700 }}>•</Typography>
                    <Typography variant="body2" sx={{ fontSize: '0.88rem', color: '#f8fafc', lineHeight: 1.5 }}>
                      {renderInlineMarkdown(trimmedLine.slice(2))}
                    </Typography>
                  </Box>
                );
              }

              // Numbered list items
              const numMatch = trimmedLine.match(/^(\d+)\.\s+(.*)/);
              if (numMatch) {
                return (
                  <Box key={lIdx} sx={{ display: 'flex', gap: 1, pl: 1.5, py: 0.1 }}>
                    <Typography variant="body2" sx={{ color: '#818cf8', fontWeight: 700 }}>{numMatch[1]}.</Typography>
                    <Typography variant="body2" sx={{ fontSize: '0.88rem', color: '#f8fafc', lineHeight: 1.5 }}>
                      {renderInlineMarkdown(numMatch[2])}
                    </Typography>
                  </Box>
                );
              }

              // Empty lines
              if (!trimmedLine) {
                return <Box key={lIdx} sx={{ height: 4 }} />;
              }

              // Normal text line
              return (
                <Typography key={lIdx} variant="body2" sx={{ fontSize: '0.88rem', color: '#e2e8f0', lineHeight: 1.6 }}>
                  {renderInlineMarkdown(line)}
                </Typography>
              );
            })}
          </Box>
        );
      })}
    </Box>
  );
}
