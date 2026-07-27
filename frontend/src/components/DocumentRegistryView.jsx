import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  TextField,
  Chip,
  Grid,
  Card,
  CardContent,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Stack,
  Divider,
  Tab,
  Tabs
} from '@mui/material';
import FolderIcon from '@mui/icons-material/Folder';
import AddIcon from '@mui/icons-material/Add';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import SearchIcon from '@mui/icons-material/Search';
import DescriptionIcon from '@mui/icons-material/Description';
import StorageIcon from '@mui/icons-material/Storage';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

export default function DocumentRegistryView({ currentProject, orgId }) {
  const projectId = currentProject?.id || 'proj_alpha_civilization';
  const [spaces, setSpaces] = useState([]);
  const [selectedSpace, setSelectedSpace] = useState('all'); // 'all' or specific space_name
  const [loading, setLoading] = useState(false);
  
  // New Space Modal State
  const [openSpaceModal, setOpenSpaceModal] = useState(false);
  const [newSpaceName, setNewSpaceName] = useState('');
  const [newSpaceDesc, setNewSpaceDesc] = useState('');

  // Document Upload State
  const [uploadText, setUploadText] = useState('');
  const [documentTitle, setDocumentTitle] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  // RAG Query State
  const [ragQuery, setRagQuery] = useState('');
  const [querying, setQuerying] = useState(false);
  const [queryResults, setQueryResults] = useState(null);

  useEffect(() => {
    fetchSpaces();
  }, [projectId]);

  const fetchSpaces = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/spaces`);
      if (res.ok) {
        const data = await res.json();
        setSpaces(data.spaces || []);
      }
    } catch (e) {
      console.error("Error fetching document spaces:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSpace = async () => {
    if (!newSpaceName.trim()) return;
    const name = newSpaceName.trim().toLowerCase().replace(/\s+/g, '_');
    try {
      const res = await fetch(`/api/projects/${projectId}/spaces?space_name=${encodeURIComponent(name)}&description=${encodeURIComponent(newSpaceDesc)}`, {
        method: 'POST'
      });
      if (res.ok) {
        setOpenSpaceModal(false);
        setNewSpaceName('');
        setNewSpaceDesc('');
        fetchSpaces();
      }
    } catch (e) {
      console.error("Error creating space:", e);
    }
  };

  const handleUploadText = async () => {
    if (!uploadText.trim() || !documentTitle.trim()) return;
    setUploading(true);
    setUploadStatus(null);
    const targetSpace = selectedSpace === 'all' ? 'default' : selectedSpace;
    try {
      const res = await fetch(`/api/projects/${projectId}/spaces/${targetSpace}/documents/upload-text?document_name=${encodeURIComponent(documentTitle)}&content=${encodeURIComponent(uploadText)}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setUploadStatus({ success: true, message: data.message });
        setUploadText('');
        setDocumentTitle('');
        fetchSpaces();
      } else {
        setUploadStatus({ success: false, message: 'Upload failed' });
      }
    } catch (e) {
      setUploadStatus({ success: false, message: e.message });
    } finally {
      setUploading(false);
    }
  };

  const handleExecuteRAGQuery = async () => {
    if (!ragQuery.trim()) return;
    setQuerying(true);
    setQueryResults(null);
    const spaceParam = selectedSpace === 'all' ? '' : `&space_name=${encodeURIComponent(selectedSpace)}`;
    try {
      const res = await fetch(`/api/projects/${projectId}/rag/query?query=${encodeURIComponent(ragQuery)}${spaceParam}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setQueryResults(data);
      }
    } catch (e) {
      console.error("RAG Query Error:", e);
    } finally {
      setQuerying(false);
    }
  };

  const [selectedFiles, setSelectedFiles] = useState([]);

  const handleUploadFiles = async () => {
    if (!selectedFiles || selectedFiles.length === 0) return;
    setUploading(true);
    setUploadStatus(null);
    const targetSpace = selectedSpace === 'all' ? 'default' : selectedSpace;
    const formData = new FormData();

    if (selectedFiles.length === 1) {
      formData.append('file', selectedFiles[0]);
      try {
        const res = await fetch(`/api/projects/${projectId}/spaces/${targetSpace}/documents/upload-file`, {
          method: 'POST',
          body: formData
        });
        if (res.ok) {
          const data = await res.json();
          setUploadStatus({ success: true, message: data.message });
          setSelectedFiles([]);
          fetchSpaces();
        } else {
          setUploadStatus({ success: false, message: 'File upload failed' });
        }
      } catch (e) {
        setUploadStatus({ success: false, message: e.message });
      } finally {
        setUploading(false);
      }
    } else {
      Array.from(selectedFiles).forEach(f => formData.append('files', f));
      try {
        const res = await fetch(`/api/projects/${projectId}/spaces/${targetSpace}/documents/upload-multiple-files`, {
          method: 'POST',
          body: formData
        });
        if (res.ok) {
          const data = await res.json();
          setUploadStatus({ success: true, message: data.message });
          setSelectedFiles([]);
          fetchSpaces();
        } else {
          setUploadStatus({ success: false, message: 'Batch file upload failed' });
        }
      } catch (e) {
        setUploadStatus({ success: false, message: e.message });
      } finally {
        setUploading(false);
      }
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, p: 3 }}>
      {/* HEADER BAR */}
      <Paper sx={{ p: 2.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'rgba(15, 23, 42, 0.75)', borderRadius: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <StorageIcon sx={{ fontSize: 32, color: '#38bdf8' }} />
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, background: 'linear-gradient(90deg, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Document Spaces & Knowledge Graph RAG
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Batch Upload Multiple Documents (PDF, PPTX, XLSX, DOCX, Markdown) • post-graph-rag Knowledge Graph Indexing
            </Typography>
          </Box>
        </Box>
        <Button
          variant="contained"
          color="primary"
          startIcon={<AddIcon />}
          onClick={() => setOpenSpaceModal(true)}
          sx={{ borderRadius: 2 }}
        >
          Create Document Space
        </Button>
      </Paper>

      {/* SPACE FILTER TABS */}
      <Paper sx={{ p: 1, backgroundColor: 'rgba(15, 23, 42, 0.6)', borderRadius: 2 }}>
        <Tabs
          value={selectedSpace}
          onChange={(e, val) => setSelectedSpace(val)}
          textColor="primary"
          indicatorColor="primary"
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab value="all" label="🌌 All Project Spaces (Space-Agnostic)" icon={<FolderIcon sx={{ fontSize: 18 }} />} iconPosition="start" />
          {spaces.map((sp) => (
            <Tab
              key={sp.space_name}
              value={sp.space_name}
              label={`${sp.space_name} (${sp.document_count || 0})`}
              icon={<DescriptionIcon sx={{ fontSize: 18 }} />}
              iconPosition="start"
            />
          ))}
        </Tabs>
      </Paper>

      <Grid container spacing={3}>
        {/* LEFT COLUMN: DOCUMENT SPACES & UPLOAD */}
        <Grid item xs={12} md={6}>
          <Stack spacing={3}>
            {/* SPACES GRID */}
            <Typography variant="subtitle1" sx={{ fontWeight: 700, color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 1 }}>
              <FolderIcon sx={{ color: '#38bdf8' }} /> Document Spaces in {projectId}
            </Typography>
            
            <Grid container spacing={2}>
              {spaces.map((sp) => (
                <Grid item xs={12} sm={6} key={sp.space_name}>
                  <Card
                    elevation={0}
                    onClick={() => setSelectedSpace(sp.space_name)}
                    sx={{
                      p: 1.5,
                      cursor: 'pointer',
                      border: `1px solid ${selectedSpace === sp.space_name ? '#38bdf8' : 'rgba(255,255,255,0.08)'}`,
                      backgroundColor: selectedSpace === sp.space_name ? 'rgba(56, 189, 248, 0.08)' : 'rgba(15, 23, 42, 0.4)',
                      transition: 'all 0.2s ease',
                      '&:hover': { borderColor: '#38bdf8' }
                    }}
                  >
                    <CardContent sx={{ p: '12px !important' }}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#f8fafc' }}>
                          {sp.space_name}
                        </Typography>
                        <Chip label={`${sp.document_count || 0} docs`} size="small" color="primary" sx={{ height: 20, fontSize: '0.65rem' }} />
                      </Stack>
                      <Typography variant="caption" sx={{ color: '#94a3b8', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {sp.description || 'Document space repository'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>

            {/* UPLOAD MULTIPLE DOCUMENT FILES CARD */}
            <Paper sx={{ p: 2.5, backgroundColor: 'rgba(15, 23, 42, 0.5)', borderRadius: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 2, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: 1 }}>
                <UploadFileIcon /> Batch Upload Multiple Files into Space: {selectedSpace}
              </Typography>

              <Stack spacing={2}>
                <Button
                  variant="outlined"
                  component="label"
                  startIcon={<UploadFileIcon />}
                  sx={{ py: 1.5, borderStyle: 'dashed' }}
                >
                  {selectedFiles.length > 0 ? `Selected ${selectedFiles.length} file(s)` : 'Select Multiple Documents (PDF, PPTX, XLSX, DOCX, TXT)'}
                  <input
                    type="file"
                    hidden
                    multiple
                    accept=".pdf,.pptx,.ppt,.xlsx,.xls,.docx,.doc,.txt,.md,.json,.csv,.html"
                    onChange={(e) => setSelectedFiles(Array.from(e.target.files))}
                  />
                </Button>

                {selectedFiles.length > 0 && (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.8, maxMaxHeight: 120, overflowY: 'auto' }}>
                    {selectedFiles.map((f, i) => (
                      <Chip key={i} label={f.name} size="small" variant="outlined" sx={{ borderColor: '#38bdf8', color: '#93c5fd' }} />
                    ))}
                  </Box>
                )}

                {selectedFiles.length > 0 && (
                  <Button
                    variant="contained"
                    color="primary"
                    onClick={handleUploadFiles}
                    disabled={uploading}
                    startIcon={uploading ? <CircularProgress size={16} /> : <UploadFileIcon />}
                  >
                    {uploading ? `Extracting & Indexing ${selectedFiles.length} files...` : `Batch Index ${selectedFiles.length} File(s) into Space '${selectedSpace}'`}
                  </Button>
                )}

                <Divider sx={{ my: 1, borderColor: 'rgba(255,255,255,0.08)' }}>OR PASTE TEXT</Divider>

                <TextField
                  fullWidth
                  size="small"
                  label="Document Title"
                  placeholder="e.g. Architecture Overview Spec"
                  value={documentTitle}
                  onChange={(e) => setDocumentTitle(e.target.value)}
                />
                <TextField
                  fullWidth
                  multiline
                  rows={3}
                  size="small"
                  label="Document Content / Text"
                  placeholder="Paste document text or markdown specification..."
                  value={uploadText}
                  onChange={(e) => setUploadText(e.target.value)}
                />
                <Button
                  variant="outlined"
                  color="primary"
                  onClick={handleUploadText}
                  disabled={uploading || !uploadText.trim() || !documentTitle.trim()}
                  startIcon={uploading ? <CircularProgress size={16} /> : <UploadFileIcon />}
                >
                  {uploading ? 'Indexing Text...' : `Index Text into Space '${selectedSpace}'`}
                </Button>
                {uploadStatus && (
                  <Chip
                    label={uploadStatus.message}
                    color={uploadStatus.success ? 'success' : 'error'}
                    sx={{ mt: 1 }}
                  />
                )}
              </Stack>
            </Paper>
          </Stack>
        </Grid>

        {/* RIGHT COLUMN: RAG QUERY TESTER */}
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5, height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'rgba(15, 23, 42, 0.5)', borderRadius: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2, color: '#818cf8', display: 'flex', alignItems: 'center', gap: 1 }}>
              <AutoAwesomeIcon /> GraphRAG Search Query (Target Space: <strong style={{ color: '#38bdf8' }}>{selectedSpace}</strong>)
            </Typography>

            <Stack direction="row" spacing={1} sx={{ mb: 3 }}>
              <TextField
                fullWidth
                size="small"
                placeholder={`Ask GraphRAG in space '${selectedSpace}'...`}
                value={ragQuery}
                onChange={(e) => setRagQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleExecuteRAGQuery()}
              />
              <Button
                variant="contained"
                color="secondary"
                onClick={handleExecuteRAGQuery}
                disabled={querying || !ragQuery.trim()}
                endIcon={querying ? <CircularProgress size={16} /> : <SearchIcon />}
              >
                Search
              </Button>
            </Stack>

            {/* RESULTS VIEW */}
            <Box sx={{ flex: 1, overflowY: 'auto', p: 2, backgroundColor: 'rgba(9, 13, 22, 0.6)', borderRadius: 2, border: '1px dashed rgba(255,255,255,0.1)' }}>
              {querying ? (
                <Stack alignItems="center" justifyContent="center" sx={{ height: 200 }}>
                  <CircularProgress color="secondary" />
                  <Typography variant="caption" sx={{ mt: 2, color: '#94a3b8' }}>
                    Searching post-graph-rag Knowledge Graph & pgvector similarity...
                  </Typography>
                </Stack>
              ) : queryResults ? (
                <Stack spacing={2}>
                  <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 700 }}>
                    QUERY MODE: {queryResults.space_name || selectedSpace}
                  </Typography>
                  <Divider sx={{ borderColor: 'rgba(255,255,255,0.08)' }} />
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', color: '#f8fafc' }}>
                    {JSON.stringify(queryResults.data, null, 2)}
                  </Typography>
                </Stack>
              ) : (
                <Stack alignItems="center" justifyContent="center" sx={{ height: 200, color: '#64748b' }}>
                  <SearchIcon sx={{ fontSize: 40, mb: 1, opacity: 0.5 }} />
                  <Typography variant="body2">Enter a question above to test GraphRAG retrieval</Typography>
                </Stack>
              )}
            </Box>
          </Paper>
        </Grid>
      </Grid>

      {/* CREATE SPACE DIALOG */}
      <Dialog open={openSpaceModal} onClose={() => setOpenSpaceModal(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, color: '#38bdf8' }}>Create Document Space</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              fullWidth
              size="small"
              label="Space Name"
              placeholder="e.g. engineering_docs"
              value={newSpaceName}
              onChange={(e) => setNewSpaceName(e.target.value)}
            />
            <TextField
              fullWidth
              multiline
              rows={2}
              size="small"
              label="Space Description"
              placeholder="e.g. Architecture specifications & design guidelines"
              value={newSpaceDesc}
              onChange={(e) => setNewSpaceDesc(e.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setOpenSpaceModal(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreateSpace} disabled={!newSpaceName.trim()}>
            Create Space
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
