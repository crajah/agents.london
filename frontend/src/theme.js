import { createTheme } from '@mui/material/styles';

const shared = {
  typography: {
    fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    h1: { fontFamily: '"Outfit", sans-serif', fontWeight: 700, letterSpacing: '-0.02em' },
    h2: { fontFamily: '"Outfit", sans-serif', fontWeight: 700, letterSpacing: '-0.02em' },
    h3: { fontFamily: '"Outfit", sans-serif', fontWeight: 700, letterSpacing: '-0.01em' },
    h4: { fontFamily: '"Outfit", sans-serif', fontWeight: 600, letterSpacing: '-0.01em' },
    h5: { fontFamily: '"Outfit", sans-serif', fontWeight: 600 },
    h6: { fontFamily: '"Outfit", sans-serif', fontWeight: 600 },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600, letterSpacing: '0.01em' },
    body2: { lineHeight: 1.6 },
    caption: { lineHeight: 1.5 },
  },
  shape: { borderRadius: 12 },
};

export const darkTheme = createTheme({
  ...shared,
  palette: {
    mode: 'dark',
    background: {
      default: '#09090b',
      paper: '#18181b',
    },
    primary: {
      main: '#6366f1',
      light: '#818cf8',
      dark: '#4f46e5',
    },
    secondary: {
      main: '#a78bfa',
      light: '#c4b5fd',
      dark: '#7c3aed',
    },
    success: { main: '#22c55e' },
    warning: { main: '#eab308' },
    error: { main: '#ef4444' },
    info: { main: '#06b6d4' },
    text: {
      primary: '#fafafa',
      secondary: '#a1a1aa',
    },
    divider: 'rgba(255,255,255,0.08)',
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(24, 24, 27, 0.8)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(255,255,255,0.06)',
          boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          padding: '8px 18px',
          boxShadow: 'none',
          fontSize: '0.85rem',
          '&:hover': { boxShadow: '0 4px 14px rgba(99,102,241,0.35)' },
        },
        containedPrimary: {
          background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
          '&:hover': { background: 'linear-gradient(135deg, #818cf8 0%, #6366f1 100%)' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 14,
          backgroundColor: 'rgba(24, 24, 27, 0.8)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(255,255,255,0.06)',
          transition: 'transform 0.15s ease, box-shadow 0.15s ease',
          '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 30px rgba(0,0,0,0.5)' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(9,9,11,0.85)',
          backdropFilter: 'blur(20px)',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500 },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8rem', minHeight: 40, textTransform: 'none' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 10 },
        },
      },
    },
  },
});

export const lightTheme = createTheme({
  ...shared,
  palette: {
    mode: 'light',
    background: {
      default: '#f8fafc',
      paper: '#ffffff',
    },
    primary: {
      main: '#4f46e5',
      light: '#6366f1',
      dark: '#3730a3',
    },
    secondary: {
      main: '#7c3aed',
      light: '#a78bfa',
      dark: '#5b21b6',
    },
    success: { main: '#16a34a' },
    warning: { main: '#ca8a04' },
    error: { main: '#dc2626' },
    info: { main: '#0891b2' },
    text: {
      primary: '#18181b',
      secondary: '#52525b',
    },
    divider: 'rgba(0,0,0,0.08)',
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#ffffff',
          border: '1px solid rgba(0,0,0,0.06)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          padding: '8px 18px',
          boxShadow: 'none',
          fontSize: '0.85rem',
          '&:hover': { boxShadow: '0 4px 14px rgba(79,70,229,0.2)' },
        },
        containedPrimary: {
          background: 'linear-gradient(135deg, #4f46e5 0%, #3730a3 100%)',
          color: '#fff',
          '&:hover': { background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)' },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 14,
          backgroundColor: '#ffffff',
          border: '1px solid rgba(0,0,0,0.06)',
          transition: 'transform 0.15s ease, box-shadow 0.15s ease',
          '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 30px rgba(0,0,0,0.1)' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(255,255,255,0.9)',
          backdropFilter: 'blur(20px)',
          borderBottom: '1px solid rgba(0,0,0,0.06)',
          color: '#18181b',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500 },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: { padding: '8px 14px' },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { fontSize: '0.8rem', minHeight: 40, textTransform: 'none' },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': { borderRadius: 10 },
        },
      },
    },
  },
});

// Default export for backward compatibility
export default darkTheme;
