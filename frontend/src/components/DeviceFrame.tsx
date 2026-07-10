/**
 * DeviceFrame - Renders content inside a browser, iPhone, or Android device frame.
 *
 * Useful for marketing screenshots so they don't bleed into the page background.
 */

import React from 'react';
import { Box } from '@mui/material';
import type { SxProps, Theme } from '@mui/material/styles';

export type DeviceVariant = 'browser' | 'iphone' | 'android';

interface DeviceFrameProps {
  variant: DeviceVariant;
  url?: string;
  children: React.ReactNode;
  sx?: SxProps<Theme>;
}

const BrowserToolbar: React.FC<{ url?: string }> = ({ url }) => (
  <Box
    sx={{
      height: 36,
      bgcolor: 'grey.100',
      borderBottom: '1px solid',
      borderColor: 'divider',
      display: 'flex',
      alignItems: 'center',
      px: 1.5,
      gap: 1,
    }}
  >
    <Box sx={{ display: 'flex', gap: 0.75 }}>
      <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#ff5f57' }} />
      <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#febc2e' }} />
      <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#28c840' }} />
    </Box>
    <Box
      sx={{
        flex: 1,
        bgcolor: 'background.paper',
        borderRadius: 1,
        height: 24,
        display: 'flex',
        alignItems: 'center',
        px: 1.5,
        fontSize: '0.75rem',
        color: 'text.secondary',
        border: '1px solid',
        borderColor: 'divider',
        maxWidth: 320,
        mx: 'auto',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        textOverflow: 'ellipsis',
      }}
    >
      {url || 'kernelworx.com'}
    </Box>
  </Box>
);

const BrowserFrame: React.FC<{ url?: string; children: React.ReactNode; sx?: SxProps<Theme> }> = ({
  url,
  children,
  sx,
}) => (
  <Box
    sx={{
      borderRadius: 2,
      overflow: 'hidden',
      bgcolor: 'background.paper',
      border: '2px solid',
      borderColor: 'grey.300',
      boxShadow: (theme) => theme.shadows[6],
      ...((sx as object) || {}),
    }}
  >
    <BrowserToolbar url={url} />
    <Box sx={{ position: 'relative', overflow: 'hidden', lineHeight: 0 }}>{children}</Box>
  </Box>
);

const PhoneFrameSvg: React.FC<{ variant: 'iphone' | 'android'; children: React.ReactNode }> = ({
  variant,
  children,
}) => {
  const isIphone = variant === 'iphone';
  const frameColor = isIphone ? '#1c1c1e' : '#1a1a1a';
  const width = 220;
  const height = 440;
  const bezel = 10;
  const screenX = bezel;
  const screenY = bezel;
  const screenW = width - bezel * 2;
  const screenH = height - bezel * 2;
  const cornerRadius = 28;
  const screenRadius = cornerRadius - bezel;

  return (
    <Box
      sx={{
        width: '100%',
        maxWidth: width,
        mx: 'auto',
        position: 'relative',
        '& svg': { display: 'block', width: '100%', height: 'auto' },
      }}
    >
      <svg viewBox={`0 0 ${width} ${height}`} xmlns="http://www.w3.org/2000/svg">
        {/* Phone body */}
        <rect x={0} y={0} width={width} height={height} rx={cornerRadius} fill={frameColor} />
        {/* Screen */}
        <rect
          x={screenX}
          y={screenY}
          width={screenW}
          height={screenH}
          rx={screenRadius}
          fill="#000"
        />
        {isIphone ? (
          <>
            {/* Dynamic Island */}
            <rect x={width / 2 - 22} y={14} width={44} height={12} rx={6} fill="#000" />
            <rect x={width / 2 - 20} y={15} width={40} height={10} rx={5} fill="#0a0a0a" />
          </>
        ) : (
          <>
            {/* Android punch-hole */}
            <circle cx={width / 2} cy={19} r={5} fill="#0a0a0a" />
          </>
        )}
      </svg>
      <Box
        sx={{
          position: 'absolute',
          top: `${(screenY / height) * 100}%`,
          left: `${(screenX / width) * 100}%`,
          width: `${(screenW / width) * 100}%`,
          height: `${(screenH / height) * 100}%`,
          overflow: 'hidden',
          borderRadius: `${screenRadius}px`,
          bgcolor: '#000',
        }}
      >
        {children}
      </Box>
    </Box>
  );
};

export const DeviceFrame: React.FC<DeviceFrameProps> = ({ variant, url, children, sx }) => {
  if (variant === 'browser') {
    return (
      <BrowserFrame url={url} sx={sx}>
        {children}
      </BrowserFrame>
    );
  }

  return <PhoneFrameSvg variant={variant}>{children}</PhoneFrameSvg>;
};
