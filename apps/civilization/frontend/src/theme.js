import { createTheme } from '@mui/material/styles';

// Design language adapted from ai.london's Modernist system:
// Archivo font, warm neutrals, sharp corners, bold borders, no gratuitous shadows.
// Brand colours: blue #537ebf, red #ea4435, yellow #f8ba17, green #7ac943.

const shared = {
  typography: {
    fontFamily: '"Archivo", system-ui, -apple-system, sans-serif',
    h1: { fontWeight: 800, fontSize: '2.625rem', lineHeight: 1.02, letterSpacing: '-0.02em' },
    h2: { fontWeight: 800, fontSize: '2rem', lineHeight: 1.05, letterSpacing: '-0.02em' },
    h3: { fontWeight: 800, fontSize: '1.5625rem', lineHeight: 1.12, letterSpacing: '-0.015em' },
    h4: { fontWeight: 800, fontSize: '1.25rem', lineHeight: 1.15, letterSpacing: '-0.01em' },
    h5: { fontWeight: 700, fontSize: '1rem', lineHeight: 1.2 },
    h6: { fontWeight: 700, fontSize: '0.8125rem', lineHeight: 1.3, letterSpacing: '0.08em', textTransform: 'uppercase' },
    subtitle1: { fontWeight: 600, fontSize: '0.9375rem', lineHeight: 1.45 },
    subtitle2: { fontWeight: 600, fontSize: '0.8125rem', lineHeight: 1.45 },
    body1: { fontWeight: 400, fontSize: '0.9375rem', lineHeight: 1.55 },
    body2: { fontWeight: 400, fontSize: '0.8125rem', lineHeight: 1.55 },
    caption: { fontWeight: 400, fontSize: '0.6875rem', lineHeight: 1.45, letterSpacing: '0.02em' },
    button: { fontWeight: 800, fontSize: '0.875rem', textTransform: 'none', letterSpacing: '0.01em' },
  },
  shape: { borderRadius: 0 },
};

// ─── Light Mode ────────────────────────────────────────────────────────────

export const lightTheme = createTheme({
  ...shared,
  palette: {
    mode: 'light',
    background: {
      default: '#f3f2f2',
      paper: '#eae9e9',
    },
    primary: {
      main: '#537ebf',
      light: '#89a9d6',
      dark: '#2f4d7a',
      contrastText: '#f3f2f2',
    },
    secondary: {
      main: '#ea4435',
      light: '#f08c80',
      dark: '#9c2a21',
    },
    success: { main: '#7ac943' },
    warning: { main: '#f8ba17', contrastText: '#201e1d' },
    error: { main: '#ea4435' },
    info: { main: '#537ebf' },
    text: {
      primary: '#201e1d',
      secondary: '#7d7979',
    },
    divider: 'rgba(32, 30, 29, 0.4)',
    action: {
      hover: 'rgba(83, 126, 191, 0.07)',
      selected: 'rgba(83, 126, 191, 0.12)',
    },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#eae9e9',
          borderRadius: 0,
          border: '2px solid #201e1d',
          boxShadow: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          padding: '8px 18px',
          boxShadow: 'none',
          fontWeight: 800,
          '&:hover': { boxShadow: 'none' },
        },
        containedPrimary: {
          backgroundColor: '#537ebf',
          color: '#f3f2f2',
          '&:hover': { backgroundColor: '#2f4d7a' },
        },
        outlined: {
          borderColor: 'rgba(32, 30, 29, 0.4)',
          '&:hover': { backgroundColor: 'rgba(32, 30, 29, 0.07)' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          backgroundColor: '#eae9e9',
          border: '2px solid #201e1d',
          boxShadow: 'none',
          transition: 'background-color 0.15s ease',
          '&:hover': { backgroundColor: '#e0dfdf' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#f3f2f2',
          borderBottom: '2px solid #201e1d',
          boxShadow: 'none',
          color: '#201e1d',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 700, borderRadius: 0, fontSize: '0.6875rem', letterSpacing: '0.02em' },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8125rem', minHeight: 40, textTransform: 'none', fontWeight: 600, borderRadius: 0 },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 0 },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 0 },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: { borderRadius: 0 },
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
      default: '#141312',
      paper: '#1e1d1c',
    },
    primary: {
      main: '#89a9d6',
      light: '#b5cbe8',
      dark: '#537ebf',
      contrastText: '#141312',
    },
    secondary: {
      main: '#f08c80',
      light: '#f6bab2',
      dark: '#ea4435',
    },
    success: { main: '#7ac943' },
    warning: { main: '#f8ba17', contrastText: '#141312' },
    error: { main: '#f08c80' },
    info: { main: '#89a9d6' },
    text: {
      primary: '#f3f2f2',
      secondary: '#9b9797',
    },
    divider: 'rgba(243, 242, 242, 0.15)',
    action: {
      hover: 'rgba(137, 169, 214, 0.1)',
      selected: 'rgba(137, 169, 214, 0.16)',
    },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#1e1d1c',
          borderRadius: 0,
          border: '1px solid rgba(243, 242, 242, 0.12)',
          boxShadow: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          padding: '8px 18px',
          boxShadow: 'none',
          fontWeight: 800,
          '&:hover': { boxShadow: 'none' },
        },
        containedPrimary: {
          backgroundColor: '#89a9d6',
          color: '#141312',
          '&:hover': { backgroundColor: '#537ebf' },
        },
        outlined: {
          borderColor: 'rgba(243, 242, 242, 0.2)',
          '&:hover': { backgroundColor: 'rgba(243, 242, 242, 0.07)' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          backgroundColor: '#1e1d1c',
          border: '1px solid rgba(243, 242, 242, 0.12)',
          boxShadow: 'none',
          transition: 'background-color 0.15s ease',
          '&:hover': { backgroundColor: '#262524' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#141312',
          borderBottom: '1px solid rgba(243, 242, 242, 0.12)',
          boxShadow: 'none',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 700, borderRadius: 0, fontSize: '0.6875rem', letterSpacing: '0.02em' },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8125rem', minHeight: 40, textTransform: 'none', fontWeight: 600, borderRadius: 0 },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 0 },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 0 },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: { borderRadius: 0 },
      },
    },
  },
});

export default darkTheme;
