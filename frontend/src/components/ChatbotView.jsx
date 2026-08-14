import React, { useState, useRef, useEffect } from 'react';
import { api, attempt } from '../utils/api';
import {
  Box, Paper, Typography, TextField, Button, Avatar, IconButton, Tooltip, List, ListItem, ListItemButton, ListItemIcon, ListItemText, CircularProgress
} from '@mui/material';
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import SendIcon from '@mui/icons-material/Send';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import PersonIcon from '@mui/icons-material/Person';
import AutoFormatDetectorRenderer from './AutoFormatDetectorRenderer';

export default function ChatbotView({ state }) {
  const projectId = state?.projectId || 'proj_alpha_civilization';
  
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [isolationMode, setIsolationMode] = useState('isolated');

  const chatEndRef = useRef(null);

  useEffect(() => {
    const storageKey = `agents_london_chatbot_${projectId}`;
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setSessions(parsed);
          setActiveSessionId(parsed[0].id);
          return;
        }
      } catch (e) {
        console.warn("Could not parse saved chat sessions:", e);
      }
    }

    const defaultSession = {
      id: `chat_${projectId}_${Date.now()}`,
      title: 'New Conversation',
      createdAt: new Date().toLocaleTimeString(),
      messages: [
        {
          id: 1,
          sender: 'agent',
          content: `Hello! I am the Civilization Chatbot for project '${projectId}'. How can I assist you today?`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]
    };

    setSessions([defaultSession]);
    setActiveSessionId(defaultSession.id);
  }, [projectId]);

  useEffect(() => {
    if (sessions.length > 0) {
      const storageKey = `agents_london_chatbot_${projectId}`;
      localStorage.setItem(storageKey, JSON.stringify(sessions));
    }
  }, [sessions, projectId]);

  const currentSession = sessions.find(s => s.id === activeSessionId) || sessions[0];

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentSession?.messages, loading]);

  const handleCreateNewSession = () => {
    const newSession = {
      id: `chat_${Date.now()}`,
      title: `Conversation #${sessions.length + 1}`,
      createdAt: new Date().toLocaleTimeString(),
      messages: [
        {
          id: Date.now(),
          sender: 'agent',
          content: `New conversation started. What's on your mind?`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]
    };
    setSessions(prev => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
  };

  const handleDeleteSession = (idToDelete, e) => {
    e.stopPropagation();
    if (sessions.length <= 1) return;
    const updated = sessions.filter(s => s.id !== idToDelete);
    setSessions(updated);
    if (activeSessionId === idToDelete) {
      setActiveSessionId(updated[0].id);
    }
  };

  const handleSendMessage = async () => {
    if (!prompt.trim() || loading) return;
    
    const userPrompt = prompt.trim();
    setPrompt('');
    setLoading(true);

    const nowStr = new Date().toLocaleTimeString();

    const userMsg = {
      id: Date.now(),
      sender: 'user',
      content: userPrompt,
      timestamp: nowStr
    };

    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        return {
          ...s,
          title: s.messages.length <= 1 ? userPrompt.substring(0, 30) + '...' : s.title,
          messages: [...s.messages, userMsg]
        };
      }
      return s;
    }));

    let agentResponseContent = "⚠️ Error: Unable to communicate with the civilization engine.";

    const { data, error } = await attempt(api.post('/api/agent/interact', {
      prompt: userPrompt,
      session_id: activeSessionId,
      isolation_mode: isolationMode,
    }));
    if (error) {
      // The failure is shown as a failure, in the transcript, where the user
      // is looking (F.12).
      agentResponseContent = `⚠️ **System Error:** ${error.userMessage}`;
    } else {
      agentResponseContent = data.final_answer || data.answer || 'No response received.';
    }

    const agentMsg = {
      id: Date.now() + 1,
      sender: 'agent',
      content: agentResponseContent,
      timestamp: new Date().toLocaleTimeString()
    };

    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        return {
          ...s,
          messages: [...s.messages, agentMsg]
        };
      }
      return s;
    }));

    setLoading(false);
  };

  return (
    <Box sx={{ display: 'flex', gap: 2, height: '100%', p: 2, overflow: 'hidden' }}>
      {/* 1. LEFT SIDEBAR: PERSISTED CHAT SESSIONS */}
      <Paper sx={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', bgcolor: 'rgba(15, 23, 42, 0.75)', borderRadius: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
        <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: 1 }}>
            <ChatBubbleOutlineIcon sx={{ fontSize: 18 }} /> Chat History
          </Typography>
          <Tooltip title="New Chat">
            <IconButton size="small" onClick={handleCreateNewSession} sx={{ color: '#38bdf8' }}>
              <AddIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>

        <List sx={{ flex: 1, overflowY: 'auto', p: 1 }}>
          {sessions.map((s) => (
            <ListItem key={s.id} disablePadding sx={{ mb: 0.5 }}>
              <ListItemButton
                selected={s.id === activeSessionId}
                onClick={() => setActiveSessionId(s.id)}
                sx={{
                  borderRadius: 2,
                  py: 1,
                  px: 1.5,
                  '&.Mui-selected': { bgcolor: 'rgba(56, 189, 248, 0.15)', borderColor: '#38bdf8' },
                  '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' }
                }}
              >
                <ListItemIcon sx={{ minWidth: 28, color: s.id === activeSessionId ? '#38bdf8' : 'text.secondary' }}>
                  <ChatBubbleOutlineIcon sx={{ fontSize: 16 }} />
                </ListItemIcon>
                <ListItemText
                  primary={s.title}
                  secondary={s.createdAt}
                  primaryTypographyProps={{ variant: 'caption', fontWeight: s.id === activeSessionId ? 700 : 500, color: s.id === activeSessionId ? '#f8fafc' : '#94a3b8', noWrap: true }}
                  secondaryTypographyProps={{ variant: 'caption', fontSize: '0.65rem', color: '#64748b' }}
                />
                {sessions.length > 1 && (
                  <IconButton size="small" onClick={(e) => handleDeleteSession(s.id, e)} sx={{ color: '#64748b', '&:hover': { color: '#ef4444' } }}>
                    <DeleteOutlineIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                )}
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Paper>

      {/* 2. MAIN CHAT AREA */}
      <Paper sx={{ flex: 1, display: 'flex', flexDirection: 'column', bgcolor: 'rgba(15, 23, 42, 0.75)', borderRadius: 3, border: '1px solid rgba(255,255,255,0.08)', overflow: 'hidden' }}>
        
        {/* Header */}
        <Box sx={{ p: 2, borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, color: '#f8fafc' }}>
              {currentSession?.title || 'Civilization Chatbot'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Project Universe: <strong style={{ color: '#38bdf8' }}>{projectId}</strong>
            </Typography>
          </Box>
        </Box>

        {/* Message Stream */}
        <Box sx={{ flex: 1, overflowY: 'auto', p: 3, display: 'flex', flexDirection: 'column', gap: 2.5, backgroundColor: 'rgba(15, 23, 42, 0.5)' }}>
          {(currentSession?.messages || []).map((msg) => (
            <Box
              key={msg.id}
              sx={{
                display: 'flex',
                justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                gap: 1.5
              }}
            >
              {msg.sender === 'agent' && (
                <Avatar sx={{ bgcolor: '#38bdf8', width: 36, height: 36 }}>
                  <SmartToyIcon sx={{ fontSize: 20 }} />
                </Avatar>
              )}

              <Box sx={{ maxWidth: '75%' }}>
                <Paper
                  elevation={0}
                  sx={{
                    p: 2,
                    borderRadius: 3,
                    backgroundColor: msg.sender === 'user' ? '#2563eb' : 'rgba(9, 13, 22, 0.85)',
                    border: msg.sender === 'user' ? 'none' : '1px solid rgba(255, 255, 255, 0.08)',
                    color: '#f8fafc',
                    whiteSpace: 'pre-line'
                  }}
                >
                  <AutoFormatDetectorRenderer content={msg.content} />
                  
                  {msg.sender === 'agent' && (
                    <Typography variant="caption" sx={{ display: 'block', mt: 1, color: '#64748b', fontSize: '0.65rem' }}>
                      {msg.timestamp}
                    </Typography>
                  )}
                </Paper>
              </Box>

              {msg.sender === 'user' && (
                <Avatar sx={{ bgcolor: '#8b5cf6', width: 36, height: 36 }}>
                  <PersonIcon sx={{ fontSize: 20 }} />
                </Avatar>
              )}
            </Box>
          ))}
          
          {loading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Avatar sx={{ bgcolor: '#38bdf8', width: 36, height: 36 }}>
                <SmartToyIcon sx={{ fontSize: 20 }} />
              </Avatar>
              <Paper elevation={0} sx={{ p: 2, borderRadius: 3, backgroundColor: 'rgba(9, 13, 22, 0.85)', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
                <CircularProgress size={20} color="primary" sx={{ display: 'block' }} />
              </Paper>
            </Box>
          )}
          <div ref={chatEndRef} />
        </Box>

        {/* Input Bar */}
        <Box sx={{ p: 2, borderTop: '1px solid rgba(255,255,255,0.08)', backgroundColor: 'rgba(15, 23, 42, 0.9)' }}>
          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
            <Typography variant="caption" color="text.secondary">Scope:</Typography>
            <Button
              size="small"
              variant={isolationMode === 'isolated' ? 'contained' : 'outlined'}
              onClick={() => setIsolationMode('isolated')}
              sx={{ fontSize: '0.65rem', py: 0.2, px: 1, minWidth: 0, textTransform: 'none' }}
            >
              This Project
            </Button>
            <Button
              size="small"
              variant={isolationMode === 'shared' ? 'contained' : 'outlined'}
              onClick={() => setIsolationMode('shared')}
              sx={{ fontSize: '0.65rem', py: 0.2, px: 1, minWidth: 0, textTransform: 'none' }}
            >
              All Projects
            </Button>
          </Box>
          <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Message the agent..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              multiline
              maxRows={4}
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: 2,
                  backgroundColor: 'rgba(0,0,0,0.2)'
                }
              }}
            />
            <Button
              variant="contained"
              color="primary"
              onClick={handleSendMessage}
              disabled={loading || !prompt.trim()}
              sx={{ minWidth: 48, width: 48, height: 48, borderRadius: '50%', p: 0 }}
            >
              <SendIcon fontSize="small" />
            </Button>
          </Box>
          <Typography variant="caption" sx={{ display: 'block', mt: 1, textAlign: 'center', color: '#64748b' }}>
            AI agents can make mistakes. Consider verifying important information.
          </Typography>
        </Box>

      </Paper>
    </Box>
  );
}
