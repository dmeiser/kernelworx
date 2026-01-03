import { createTheme } from '@mui/material/styles';

// Branding colors
const primary = '#1976d2';
const secondary = '#dc004e';

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: primary },
    secondary: { main: secondary },
    background: { default: '#f5f5f5' },
    text: { primary: '#333333' },
  },
  typography: {
    fontFamily: [
      '"Atkinson Hyperlegible"',
      '"Lexend"',
      '"Inter"',
      '-apple-system',
      'BlinkMacSystemFont',
      '"Segoe UI"',
      'Roboto',
      '"Helvetica Neue"',
      'Arial',
      'sans-serif',
    ].join(','),
    // Base font size - slightly larger on mobile for readability
    fontSize: 15,
    body1: {
      fontSize: '1rem',
      '@media (max-width: 600px)': {
        fontSize: '0.9375rem', // 15px on mobile
      },
    },
    body2: {
      fontSize: '0.875rem',
      '@media (max-width: 600px)': {
        fontSize: '0.8125rem', // 13px on mobile
      },
    },
    h1: {
      fontFamily: '"Kaushan Script", "Atkinson Hyperlegible", cursive',
      fontWeight: 600,
      letterSpacing: '0.08em',
      fontSize: '2rem',
      '@media (min-width: 900px)': {
        fontSize: '3rem',
      },
    },
    h2: {
      fontFamily: '"Atkinson Hyperlegible", "Lexend", "Inter", sans-serif',
      fontWeight: 700,
      fontSize: '1.75rem',
      '@media (max-width: 600px)': {
        fontSize: '1.5rem',
      },
    },
    h3: {
      fontFamily: '"Atkinson Hyperlegible", "Lexend", "Inter", sans-serif',
      fontWeight: 700,
      fontSize: '1.5rem',
      '@media (max-width: 600px)': {
        fontSize: '1.25rem',
      },
    },
    h4: {
      fontSize: '1.5rem',
      fontWeight: 600,
      '@media (max-width: 600px)': {
        fontSize: '1.25rem',
      },
    },
    h5: {
      fontSize: '1.25rem',
      fontWeight: 600,
      '@media (max-width: 600px)': {
        fontSize: '1.125rem',
      },
    },
    h6: {
      fontSize: '1.125rem',
      fontWeight: 600,
      '@media (max-width: 600px)': {
        fontSize: '1rem',
      },
    },
    button: {
      textTransform: 'none',
      fontWeight: 500,
      fontSize: '0.9375rem',
      '@media (max-width: 600px)': {
        fontSize: '0.875rem',
      },
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          minWidth: 0,
          overflowX: 'auto',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          '@media (max-width: 600px)': {
            paddingTop: '6px',
            paddingBottom: '6px',
            paddingLeft: '12px',
            paddingRight: '12px',
            minHeight: '36px',
          },
        },
        sizeLarge: {
          '@media (max-width: 600px)': {
            paddingTop: '8px',
            paddingBottom: '8px',
            fontSize: '0.9375rem',
          },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          '@media (max-width: 600px)': {
            padding: '8px',
          },
        },
      },
    },
  },
});
