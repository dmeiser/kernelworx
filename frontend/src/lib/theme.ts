import { createTheme } from '@mui/material/styles';

// KernelWorx brand tokens (from docs/branding/system/variables.css)
export const brand = {
  primary: {
    1: '#ebf8ff',
    2: '#c2e9ff',
    3: '#94d0f7',
    5: '#3e94de',
    6: '#1976d2',
    7: '#0c57ab',
    9: '#00265e',
    link: '#005a9c',
  },
  success: {
    main: '#388e3c',
    bg: '#c4cfc2',
    border: '#9fb59e',
    hover: '#569c56',
    active: '#15431c',
  },
  warning: {
    main: '#f57c00',
    bg: '#fff7e6',
    border: '#ffcb7a',
    hover: '#ff9c29',
    active: '#8a4200',
  },
  error: {
    main: '#dc004e',
    bg: '#ffe6ea',
    border: '#ff7a9c',
    hover: '#e82564',
    active: '#b50046',
    text: '#9e0036',
  },
  text: {
    primary: '#4b4b4b',
    secondary: '#595959',
    tertiary: '#595959',
    quaternary: '#757575',
  },
  fill: {
    main: '#e0e0e0',
    secondary: '#f3f3f3',
    tertiary: '#f7f7f7',
    quaternary: '#fbfbfb',
  },
  background: {
    layout: '#f7f7f7',
    container: '#ffffff',
  },
  border: {
    main: '#e0e0e0',
    secondary: '#f3f3f3',
  },
  radius: {
    sm: '3px',
    md: '4px',
    lg: '6px',
  },
  size: {
    xs: 8,
    sm: 12,
    xl: 24,
  },
  controlHeight: {
    sm: 24,
    md: 32,
    lg: 40,
  },
  motion: {
    durationMid: '0.2s',
    easeInOut: 'cubic-bezier(0.645, 0.045, 0.355, 1)',
  },
};

const bodyFont = [
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
].join(',');

export const displayFont = [
  '"Bricolage Grotesque"',
  '"Atkinson Hyperlegible"',
  'sans-serif',
].join(',');

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: brand.primary[6],
      light: brand.primary[5],
      dark: brand.primary[7],
      contrastText: '#ffffff',
    },
    secondary: {
      main: brand.error.main,
      light: brand.error.hover,
      dark: brand.error.active,
      contrastText: '#ffffff',
    },
    error: {
      main: brand.error.main,
      light: brand.error.hover,
      dark: brand.error.active,
    },
    warning: {
      main: brand.warning.main,
      light: brand.warning.hover,
      dark: brand.warning.active,
    },
    info: {
      main: brand.primary[6],
      light: brand.primary[2],
      dark: brand.primary[7],
    },
    success: {
      main: brand.success.main,
      light: brand.success.hover,
      dark: brand.success.active,
    },
    background: {
      default: brand.background.layout,
      paper: brand.background.container,
    },
    text: {
      primary: brand.text.primary,
      secondary: brand.text.secondary,
      disabled: brand.text.tertiary,
    },
    divider: brand.border.main,
    grey: {
      50: '#fbfbfb',
      100: '#f7f7f7',
      200: '#f3f3f3',
      300: '#e0e0e0',
      400: '#cccccc',
      500: '#a3a3a3',
      600: '#7a7a7a',
      700: '#4b4b4b',
      800: '#333333',
      900: '#1a1a1a',
    },
  },
  typography: {
    fontFamily: bodyFont,
    fontSize: 14,
    fontWeightLight: 400,
    fontWeightRegular: 400,
    fontWeightMedium: 600,
    fontWeightBold: 700,
    h1: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: 'clamp(36px, 5.6vw, 64px)',
      letterSpacing: '-0.025em',
      lineHeight: 1.06,
      color: brand.text.primary,
    },
    h2: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: 'clamp(26px, 3.2vw, 38px)',
      letterSpacing: '-0.015em',
      lineHeight: 1.15,
      color: brand.text.primary,
    },
    h3: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: 'clamp(22px, 2.6vw, 30px)',
      letterSpacing: '-0.015em',
      lineHeight: 1.2,
      color: brand.text.primary,
    },
    h4: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: '22px',
      lineHeight: 1.25,
      color: brand.text.primary,
    },
    h5: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: '18px',
      lineHeight: 1.3,
      color: brand.text.primary,
    },
    h6: {
      fontFamily: displayFont,
      fontWeight: 600,
      fontSize: '16px',
      lineHeight: 1.35,
      color: brand.text.primary,
    },
    body1: {
      fontSize: '1rem',
      lineHeight: 1.5714285714285714,
      color: brand.text.primary,
      '@media (max-width: 600px)': {
        fontSize: '0.9375rem',
      },
    },
    body2: {
      fontSize: '0.875rem',
      lineHeight: 1.5714285714285714,
      color: brand.text.secondary,
      '@media (max-width: 600px)': {
        fontSize: '0.8125rem',
      },
    },
    subtitle1: {
      fontSize: '1.125rem',
      lineHeight: 1.5,
      color: brand.text.secondary,
    },
    subtitle2: {
      fontSize: '0.875rem',
      lineHeight: 1.5,
      color: brand.text.secondary,
      fontWeight: 600,
    },
    button: {
      textTransform: 'none',
      fontWeight: 600,
      fontSize: '0.875rem',
      lineHeight: 1,
      '@media (max-width: 600px)': {
        fontSize: '0.8125rem',
      },
    },
    caption: {
      fontSize: '0.75rem',
      lineHeight: 1.5,
      color: brand.text.tertiary,
    },
    overline: {
      fontSize: '0.75rem',
      fontWeight: 600,
      letterSpacing: '0.14em',
      lineHeight: 1,
      textTransform: 'uppercase',
      color: brand.primary.link,
    },
  },
  shape: {
    borderRadius: 4,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          minWidth: 0,
          overflowX: 'auto',
          backgroundColor: brand.background.layout,
          color: brand.text.primary,
        },
        a: {
          color: brand.primary.link,
          textDecoration: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: brand.radius.md,
          transition: `all ${brand.motion.durationMid} ${brand.motion.easeInOut}`,
          minWidth: 'auto',
          '&:hover': {
            filter: 'brightness(1.07)',
          },
          '&:active': {
            filter: 'brightness(0.95)',
            transform: 'translateY(0.5px)',
          },
        },
        sizeSmall: {
          height: brand.controlHeight.sm,
          padding: `0 ${brand.size.xs}px`,
          fontSize: '0.75rem',
        },
        sizeMedium: {
          height: brand.controlHeight.md,
          padding: `0 ${brand.size.sm}px`,
          fontSize: '0.875rem',
        },
        sizeLarge: {
          height: brand.controlHeight.lg,
          padding: `0 ${brand.size.xl}px`,
          fontSize: '1.125rem',
        },
        containedPrimary: {
          backgroundColor: brand.primary[7],
          color: '#ffffff',
          border: `1px solid ${brand.primary[7]}`,
          boxShadow: `0 2px 0 ${brand.primary[1]}`,
          '&:hover': {
            backgroundColor: brand.primary[7],
            borderColor: brand.primary[7],
          },
          '&:active': {
            backgroundColor: brand.primary[9],
            borderColor: brand.primary[9],
          },
          '&:disabled': {
            backgroundColor: brand.fill.main,
            color: brand.text.tertiary,
            borderColor: brand.fill.main,
            boxShadow: 'none',
          },
        },
        containedSecondary: {
          backgroundColor: brand.error.text,
          color: '#ffffff',
          border: `1px solid ${brand.error.text}`,
          boxShadow: `0 2px 0 ${brand.error.bg}`,
          '&:hover': {
            backgroundColor: brand.error.text,
            borderColor: brand.error.text,
          },
          '&:active': {
            backgroundColor: brand.error.active,
            borderColor: brand.error.active,
          },
          '&:disabled': {
            backgroundColor: brand.fill.main,
            color: brand.text.tertiary,
            borderColor: brand.fill.main,
            boxShadow: 'none',
          },
        },
        outlinedPrimary: {
          backgroundColor: brand.background.container,
          color: brand.primary.link,
          border: `1px solid ${brand.primary.link}`,
          '&:hover': {
            backgroundColor: brand.primary[1],
            borderColor: brand.primary.link,
          },
          '&:active': {
            backgroundColor: brand.primary[2],
          },
          '&:disabled': {
            color: brand.text.tertiary,
            borderColor: brand.border.main,
            backgroundColor: brand.background.container,
          },
        },
        outlinedSecondary: {
          backgroundColor: brand.background.container,
          color: brand.error.main,
          border: `1px solid ${brand.error.main}`,
          '&:hover': {
            backgroundColor: brand.error.bg,
          },
          '&:disabled': {
            color: brand.text.tertiary,
            borderColor: brand.border.main,
          },
        },
        text: {
          color: brand.primary.link,
          backgroundColor: 'transparent',
          borderColor: 'transparent',
          '&:hover': {
            backgroundColor: 'transparent',
            color: brand.primary.link,
            textDecoration: 'underline',
          },
          '&:active': {
            color: brand.primary[9],
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundColor: brand.background.container,
          border: `1px solid ${brand.border.secondary}`,
          borderRadius: brand.radius.lg,
          boxShadow: `0 1px 2px ${brand.fill.quaternary}`,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
        elevation1: {
          boxShadow: `0 1px 2px ${brand.fill.quaternary}`,
        },
        elevation2: {
          boxShadow: `0 8px 28px -16px ${brand.fill.secondary}`,
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: brand.radius.md,
          backgroundColor: brand.background.container,
          height: brand.controlHeight.md,
          transition: `border-color ${brand.motion.durationMid} ${brand.motion.easeInOut}`,
          '& fieldset': {
            borderColor: brand.border.main,
            borderWidth: '1px',
            transition: `border-color ${brand.motion.durationMid} ${brand.motion.easeInOut}`,
          },
          '&:hover fieldset': {
            borderColor: brand.primary[3],
          },
          '&.Mui-focused fieldset': {
            borderColor: brand.primary[6],
            borderWidth: '1px',
          },
          '&.Mui-focused': {
            boxShadow: `0 0 0 3px ${brand.primary[1]}`,
          },
          '&.Mui-disabled': {
            backgroundColor: brand.fill.tertiary,
          },
          '&.Mui-error fieldset': {
            borderColor: brand.error.main,
          },
          '&.MuiInputBase-multiline': {
            height: 'auto',
          },
        },
        input: {
          padding: `0 ${brand.size.sm}px`,
          fontSize: '0.875rem',
          '&::placeholder': {
            color: brand.text.quaternary,
            opacity: 1,
          },
        },
        sizeSmall: {
          height: brand.controlHeight.sm,
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          color: brand.text.secondary,
          fontSize: '0.8125rem',
          '&.Mui-focused': {
            color: brand.primary.link,
          },
          '&.Mui-error': {
            color: brand.error.main,
          },
          '&.MuiInputLabel-outlined': {
            transform: 'translate(14px, 7px) scale(1)',
            '&.MuiInputLabel-shrink': {
              transform: 'translate(14px, -7px) scale(0.75)',
            },
            '&.MuiInputLabel-sizeSmall': {
              transform: 'translate(14px, 3px) scale(1)',
              '&.MuiInputLabel-shrink': {
                transform: 'translate(14px, -6px) scale(0.75)',
              },
            },
          },
        },
      },
    },
    MuiFormHelperText: {
      styleOverrides: {
        root: {
          color: brand.text.tertiary,
          fontSize: '0.75rem',
          marginTop: '4px',
          '&.Mui-error': {
            color: brand.error.main,
          },
        },
      },
    },
    MuiLink: {
      styleOverrides: {
        root: {
          color: brand.primary.link,
          textDecoration: 'none',
          fontWeight: 600,
          '&:hover': {
            color: brand.primary.link,
            textDecoration: 'underline',
          },
          '&:active': {
            color: brand.primary[9],
          },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: 'rgba(255, 255, 255, 0.86)',
          color: brand.text.primary,
          boxShadow: `0 1px 0 ${brand.border.secondary}`,
          backdropFilter: 'blur(12px)',
        },
        colorPrimary: {
          backgroundColor: brand.primary[7],
          color: '#ffffff',
          boxShadow: 'none',
          backdropFilter: 'none',
        },
      },
    },
    MuiToolbar: {
      styleOverrides: {
        root: {
          minHeight: '64px',
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          color: brand.text.secondary,
          '&:hover': {
            backgroundColor: brand.fill.tertiary,
          },
          '@media (max-width: 600px)': {
            padding: '8px',
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: brand.radius.md,
        },
        standardError: {
          backgroundColor: brand.error.bg,
          color: brand.error.text,
          border: `1px solid ${brand.error.border}`,
        },
        standardSuccess: {
          backgroundColor: brand.success.bg,
          color: brand.success.active,
          border: `1px solid ${brand.success.border}`,
        },
        standardInfo: {
          backgroundColor: brand.primary[1],
          color: brand.primary[9],
          border: `1px solid ${brand.primary[3]}`,
        },
        standardWarning: {
          backgroundColor: brand.warning.bg,
          color: brand.warning.active,
          border: `1px solid ${brand.warning.border}`,
        },
      },
    },
    MuiAccordion: {
      styleOverrides: {
        root: {
          backgroundColor: 'transparent',
          boxShadow: 'none',
          borderBottom: `1px solid ${brand.border.main}`,
          '&::before': {
            display: 'none',
          },
        },
      },
    },
    MuiAccordionSummary: {
      styleOverrides: {
        root: {
          padding: '0',
          minHeight: '56px',
          '& .MuiAccordionSummary-content': {
            margin: '16px 0',
            fontWeight: 600,
            fontSize: '1.125rem',
            color: brand.text.primary,
          },
        },
      },
    },
    MuiAccordionDetails: {
      styleOverrides: {
        root: {
          padding: '0 0 20px',
          color: brand.text.secondary,
          maxWidth: '70ch',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: brand.radius.sm,
          fontWeight: 600,
          fontSize: '0.75rem',
        },
        filledPrimary: {
          backgroundColor: brand.primary[7],
          color: '#ffffff',
          border: `1px solid ${brand.primary[7]}`,
        },
      },
    },
  },
});
