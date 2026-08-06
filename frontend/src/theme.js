import { createTheme } from '@mui/material/styles';

const shared = {
  typography: {
    fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    h1: { fontFamily: '"Outfit", sans-serif', fontWeight: 700, letterSpacing: '-0.025em', fontSize: '2.25rem' },
    h2: { fontFamily: '"Outfit", sans-serif', fontWeight: 700, letterSpacing: '-0.02em', fontSize: '1.875rem' },
    h3: { fontFamily: '"Outfit", sans-serif', fontWeight: 600, letterSpacing: '-0.015em', fontSize: '1.5rem' },
    h4: { fontFamily: '"Outfit", sans-serif', fontWeight: 600, letterSpacing: '-0.01em', fontSize: '1.25rem' },
    h5: { fontFamily: '"Inter", sans-serif', fontWeight: 600, fontSize: '1.1rem' },
    h6: { fontFamily: '"Inter", sans-serif', fontWeight: 600, fontSize: '1rem' },
    subtitle1: { fontWeight: 500, fontSize: '0.95rem', lineHeight: 1.5 },
    subtitle2: { fontWeight: 600, fontSize: '0.85rem', lineHeight: 1.5 },
    body1: { fontSize: '0.9rem', lineHeight: 1.65, letterSpacing: '0.01em' },
    body2: { fontSize: '0.825rem', lineHeight: 1.6, letterSpacing: '0.01em' },
    caption: { fontSize: '0.75rem', lineHeight: 1.5, letterSpacing: '0.02em' },
    button: { textTransform: 'none', fontWeight: 600, fontSize: '0.85rem', letterSpacing: '0.01em' },
  },
  shape: { borderRadius: 10 },
};

// ─── Light Mode ────────────────────────────────────────────────────────────

export const lightTheme = createTheme({
  ...shared,
  palette: {
    mode: 'light',
    background: {
      default: '#F8FAFC',
      paper: '#FFFFFF',
    },
    primary: {
      main: '#1A73E8',
      light: '#4285F4',
      dark: '#1557B0',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: '#7C3AED',
      light: '#A78BFA',
      dark: '#5B21B6',
    },
    success: { main: '#1E8E3E', light: '#34A853', contrastText: '#FFFFFF' },
    warning: { main: '#F9AA33', light: '#FBC02D', contrastText: '#0B132B' },
    error: { main: '#E53935', light: '#FF6B6B', contrastText: '#FFFFFF' },
    info: { main: '#1A73E8', light: '#4285F4' },
    text: {
      primary: '#0B132B',
      secondary: '#4A5568',
    },
    divider: 'rgba(11, 19, 43, 0.08)',
    action: {
      hover: 'rgba(26, 115, 232, 0.06)',
      selected: 'rgba(26, 115, 232, 0.1)',
    },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#FFFFFF',
          border: '1px solid rgba(11, 19, 43, 0.08)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.03)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          padding: '8px 20px',
          boxShadow: 'none',
          fontWeight: 600,
          '&:hover': { boxShadow: '0 1px 3px rgba(26,115,232,0.2)' },
        },
        containedPrimary: {
          backgroundColor: '#1A73E8',
          '&:hover': { backgroundColor: '#1557B0' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          backgroundColor: '#FFFFFF',
          border: '1px solid rgba(11, 19, 43, 0.08)',
          transition: 'box-shadow 0.2s ease',
          '&:hover': { boxShadow: '0 4px 16px rgba(0,0,0,0.08)' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(255, 255, 255, 0.92)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(11, 19, 43, 0.08)',
          color: '#0B132B',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500, fontSize: '0.75rem' },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8rem', minHeight: 40, textTransform: 'none', fontWeight: 500 },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 8 },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
  },
});

// ─── Dark Mode ─────────────────────────────────────────────────────────────

export const darkTheme = createTheme({
  ...shared,
  palette: {
    mode: 'dark',
    background: {
      default: '#0F1219',
      paper: '#293249',
    },
    primary: {
      main: '#4285F4',
      light: '#6EA8FE',
      dark: '#1A73E8',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: '#A78BFA',
      light: '#C4B5FD',
      dark: '#7C3AED',
    },
    success: { main: '#34A853', light: '#4CAF50' },
    warning: { main: '#FBC02D', light: '#FFCA28', contrastText: '#0F1219' },
    error: { main: '#FF6B6B', light: '#FF8A80' },
    info: { main: '#4285F4', light: '#6EA8FE' },
    text: {
      primary: '#F1F5F9',
      secondary: '#94A3B8',
    },
    divider: 'rgba(241, 245, 249, 0.08)',
    action: {
      hover: 'rgba(66, 133, 244, 0.1)',
      selected: 'rgba(66, 133, 244, 0.16)',
    },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#293249',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(241, 245, 249, 0.06)',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          padding: '8px 20px',
          boxShadow: 'none',
          fontWeight: 600,
          '&:hover': { boxShadow: '0 2px 8px rgba(66,133,244,0.3)' },
        },
        containedPrimary: {
          backgroundColor: '#4285F4',
          '&:hover': { backgroundColor: '#1A73E8' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          backgroundColor: '#293249',
          border: '1px solid rgba(241, 245, 249, 0.06)',
          transition: 'box-shadow 0.2s ease',
          '&:hover': { boxShadow: '0 4px 20px rgba(0,0,0,0.4)' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(15, 18, 25, 0.92)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(241, 245, 249, 0.06)',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500, fontSize: '0.75rem' },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8rem', minHeight: 40, textTransform: 'none', fontWeight: 500 },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 8 },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
  },
});

export default darkTheme;
