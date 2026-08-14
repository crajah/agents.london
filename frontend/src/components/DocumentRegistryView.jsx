import React, { useState, useEffect, useCallback } from 'react';
import { api, attempt } from '../utils/api';
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
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Stack,
  Divider,
  Tab,
  Tabs,
  Alert
, LinearProgress} from '@mui/material';
import FolderIcon from '@mui/icons-material/Folder';
import AddIcon from '@mui/icons-material/Add';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import SearchIcon from '@mui/icons-material/Search';
import DescriptionIcon from '@mui/icons-material/Description';
import StorageIcon from '@mui/icons-material/Storage';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import HubIcon from '@mui/icons-material/Hub';
import GraphRAGExplorer from './GraphRAGExplorer';

export default function DocumentRegistryView({ currentProject, orgId }) {
  const projectId = currentProject?.id || 'proj_alpha_civilization';
  const [spaces, setSpaces] = useState([]);
  const [selectedSpace, setSelectedSpace] = useState('all');
  const [loadError, setLoadError] = useState(null);
  const [queryError, setQueryError] = useState(null); // 'all' or specific space_name
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

  const [documents, setDocuments] = useState([]);
  const [viewMode, setViewMode] = useState('documents'); // 'documents' | 'graph'

  // Every call goes through the API module, which attaches the organisation
  // and the project. This panel used to send neither, so uploads, listings and
  // queries all landed in whichever realm the backend defaults to rather than
  // the signed-in user's (F.28).
  //
  // Both loaders are declared before the effect that runs them and memoised on
  // what they actually read. They used to be plain functions declared below it,
  // which worked only because an effect runs after the whole body has been
  // evaluated — and left the effect's dependency list lying about what it
  // depends on, so a project switch could serve the previous project's
  // documents.
  const fetchSpaces = useCallback(async () => {
    setLoading(true);
    const { data, error } = await attempt(api.get(`/api/projects/${projectId}/spaces`));
    if (error) { setLoadError(error); setSpaces([]); }
    else { setLoadError(null); setSpaces(data.spaces || []); }
    setLoading(false);
  }, [projectId]);

  const fetchDocuments = useCallback(async () => {
    const { data, error } = await attempt(api.get(
      `/api/projects/${projectId}/documents`,
      { params: selectedSpace === 'all' ? {} : { space_name: selectedSpace } }));
    if (error) { setLoadError(error); setDocuments([]); }
    else { setDocuments(data.documents || []); }
  }, [projectId, selectedSpace]);

  useEffect(() => {
    fetchSpaces();
    fetchDocuments();
  }, [fetchSpaces, fetchDocuments]);

  const handleCreateSpace = async () => {
    if (!newSpaceName.trim()) return;
    const name = newSpaceName.trim().toLowerCase().replace(/\s+/g, '_');
    const { error } = await attempt(api.post(
      `/api/projects/${projectId}/spaces`, undefined,
      { params: { space_name: name, description: newSpaceDesc } }));
    if (error) { setUploadStatus({ success: false, message: error.userMessage }); return; }
    setOpenSpaceModal(false);
    setNewSpaceName('');
    setNewSpaceDesc('');
    fetchSpaces();
    fetchDocuments();
  };

  /**
   * The registry distinguishes indexed from catalogued-but-not-indexed and says
   * which (document-registry Rule 6.2). A document that uploaded but is not
   * retrievable must not be presented as filed (F.29), and a batch shows its
   * per-file outcomes rather than one count (F.31).
   */
  const reportIngest = (data) => {
    const indexed = data?.indexed !== false && data?.status !== 'partial';
    setUploadStatus({
      success: indexed,
      partial: !indexed,
      message: data?.message || (indexed ? 'Indexed.' : 'Catalogued, but not indexed.'),
      failures: data?.failures || [],
      counts: data?.failed_count !== undefined
        ? { indexed: data.indexed_count ?? data.count ?? 0, failed: data.failed_count }
        : null,
    });
  };

  const handleUploadText = async () => {
    if (!uploadText.trim() || !documentTitle.trim()) return;
    setUploading(true);
    setUploadStatus(null);
    const targetSpace = selectedSpace === 'all' ? 'default' : selectedSpace;
    const { data, error } = await attempt(api.post(
      `/api/projects/${projectId}/spaces/${targetSpace}/documents/upload-text`,
      undefined, { params: { document_name: documentTitle, content: uploadText } }));
    if (error) setUploadStatus({ success: false, message: error.userMessage });
    else {
      reportIngest(data);
      setUploadText('');
      setDocumentTitle('');
      fetchSpaces();
      fetchDocuments();
    }
    setUploading(false);
  };

  const handleExecuteRAGQuery = async () => {
    if (!ragQuery.trim()) return;
    setQuerying(true);
    setQueryResults(null);
    setQueryError(null);
    const { data, error } = await attempt(api.post(
      `/api/projects/${projectId}/rag/query`, undefined,
      { params: { query: ragQuery,
                  ...(selectedSpace === 'all' ? {} : { space_name: selectedSpace }) } }));
    // An empty corpus and an unreachable one are opposite answers (F.38).
    if (error) setQueryError(error); else setQueryResults(data);
    setQuerying(false);
  };

  const [selectedFiles, setSelectedFiles] = useState([]);

  const handleUploadFiles = async () => {
    if (!selectedFiles || selectedFiles.length === 0) return;
    setUploading(true);
    setUploadStatus(null);
    const targetSpace = selectedSpace === 'all' ? 'default' : selectedSpace;
    const many = selectedFiles.length > 1;

    const { data, error } = await attempt(api.upload(
      `/api/projects/${projectId}/spaces/${targetSpace}/documents/` +
      (many ? 'upload-multiple-files' : 'upload-file'),
      { files: many
          ? Array.from(selectedFiles).map((file) => ({ name: 'files', file }))
          : [{ name: 'file', file: selectedFiles[0] }] }));

    if (error) {
      // A 415 means no parser could read the file and nothing was stored
      // (document-registry Rule 5.3). The user's next question is whether to
      // re-upload, so the reason travels with the message (F.30).
      setUploadStatus({
        success: false,
        message: error.status === 415
          ? `${error.userMessage} Nothing was stored — try a different format.`
          : error.userMessage,
      });
    } else {
      reportIngest(data);
      setSelectedFiles([]);
      fetchSpaces();
      fetchDocuments();
    }
    setUploading(false);
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3, p: 3 }}>
      {/* Set on every load and rendered nowhere, so a slow project looked
          like an empty one. */}
      {loading && <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />}
      {loadError && (
        <Alert severity="error" onClose={() => setLoadError(null)}>
          {loadError.userMessage}
          <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
            This is not an empty project — the corpus could not be read.
          </Typography>
        </Alert>
      )}

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
        <Stack direction="row" spacing={1}>
          <Button
            variant={viewMode === 'documents' ? 'contained' : 'outlined'}
            size="small"
            startIcon={<DescriptionIcon />}
            onClick={() => setViewMode('documents')}
            sx={{ borderRadius: 2 }}
          >
            Documents
          </Button>
          <Button
            variant={viewMode === 'graph' ? 'contained' : 'outlined'}
            size="small"
            color="secondary"
            startIcon={<HubIcon />}
            onClick={() => setViewMode('graph')}
            sx={{ borderRadius: 2 }}
          >
            Graph Explorer
          </Button>
          {viewMode === 'documents' && (
            <Button
              variant="contained"
              color="primary"
              size="small"
              startIcon={<AddIcon />}
              onClick={() => setOpenSpaceModal(true)}
              sx={{ borderRadius: 2 }}
            >
              Create Space
            </Button>
          )}
        </Stack>
      </Paper>

      {viewMode === 'graph' ? (
        <GraphRAGExplorer projectId={projectId} orgId={orgId} spaceName={selectedSpace} />
      ) : (
      <>
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
          <Tab value="all" label="🌌 All document spaces in this project" icon={<FolderIcon sx={{ fontSize: 18 }} />} iconPosition="start" />
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
              <FolderIcon sx={{ color: '#38bdf8' }} /> Document spaces in project {projectId}
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
                  {uploading ? 'Indexing Text...' : `Index text into document space '${selectedSpace}'`}
                </Button>
                {uploadStatus && (
                  <Alert
                    severity={uploadStatus.success ? 'success'
                              : uploadStatus.partial ? 'warning' : 'error'}
                    sx={{ mt: 1 }}
                    onClose={() => setUploadStatus(null)}
                  >
                    {uploadStatus.message}
                    {/* Catalogued but not indexed is a real state, and the
                        document is not retrievable until it is reindexed
                        (document-registry Rule 6.2). */}
                    {uploadStatus.partial && (
                      <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                        This document is catalogued but not searchable yet.
                      </Typography>
                    )}
                    {uploadStatus.counts && (
                      <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                        {uploadStatus.counts.indexed} indexed,{' '}
                        {uploadStatus.counts.failed} failed.
                      </Typography>
                    )}
                    {(uploadStatus.failures || []).map((f) => (
                      <Typography key={f.filename} variant="caption" display="block">
                        • {f.filename} — {f.stage}: {f.error}
                      </Typography>
                    ))}
                  </Alert>
                )}
              </Stack>
            </Paper>

            {/* PERSISTENT DOCUMENTS CATALOG */}
            <Paper sx={{ p: 2.5, backgroundColor: 'rgba(15, 23, 42, 0.5)', borderRadius: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: 1 }}>
                <DescriptionIcon /> Persistent Document Catalog ({documents.length})
              </Typography>
              {documents.length === 0 ? (
                <Typography variant="caption" color="text.secondary">
                  No documents persisted in space ‘{selectedSpace}’ yet. Upload files or text above.
                </Typography>
              ) : (
                <Stack spacing={1} sx={{ maxHeight: 220, overflowY: 'auto' }}>
                  {documents.map((doc, idx) => (
                    <Paper key={idx} elevation={0} sx={{ p: 1.2, bgcolor: 'rgba(9, 13, 22, 0.7)', borderRadius: 2, border: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.82rem' }} noWrap>
                          {doc.document_name || doc.filename || 'Uploaded Document'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                          Space: <strong style={{ color: '#38bdf8' }}>{doc.space_name}</strong> • Method: {doc.extraction_method || 'api'} • Length: {doc.content_length || 0} chars
                        </Typography>
                      </Box>
                      <Chip label="Persisted (post-graph)" size="small" color="primary" sx={{ height: 18, fontSize: '0.6rem' }} />
                    </Paper>
                  ))}
                </Stack>
              )}
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
              ) : queryError ? (
                <Alert severity="error">
                  {queryError.userMessage}
                  <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                    Nobody answered — this does not mean the corpus is empty.
                  </Typography>
                </Alert>
              ) : queryResults ? (
                <Stack spacing={2}>
                  <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 700 }}>
                    DOCUMENT SPACE: {queryResults.document_space || queryResults.space_name || selectedSpace}
                  </Typography>
                  {/* An agent citing this passage is claiming provenance, so
                      the engine that answered is named (F.32). */}
                  <Typography variant="caption" sx={{ color: queryResults.status === 'degraded' ? '#fbbf24' : '#94a3b8' }}>
                    engine: {queryResults.engine || 'unknown'}
                    {queryResults.status === 'degraded' ? ' — DEGRADED' : ''}
                  </Typography>
                  {queryResults.warning && (
                    <Alert severity="warning">{queryResults.warning}</Alert>
                  )}
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

      </>
      )}

      {/* CREATE SPACE DIALOG */}
      <Dialog open={openSpaceModal} onClose={() => setOpenSpaceModal(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, color: '#38bdf8' }}>Create document space</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              fullWidth
              size="small"
              label="Document space name"
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
