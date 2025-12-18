/**
 * DevFooter - Shows version info in development environments
 * Displayed at the bottom of every page for easy debugging
 */

import React from "react";
import { Box, Typography, Tooltip } from "@mui/material";
import { getVersionString, getDetailedBuildInfo, isDevelopment, getShortBuildTime } from "../lib/buildInfo";

export const DevFooter: React.FC = () => {
  if (!isDevelopment()) {
    return null;
  }

  return (
    <Box
      component="footer"
      sx={{
        position: { xs: "relative", sm: "fixed" },
        bottom: 0,
        left: 0,
        right: 0,
        py: 0.5,
        px: 2,
        bgcolor: "rgba(0, 0, 0, 0.7)",
        backdropFilter: "blur(4px)",
        zIndex: 1000,
        textAlign: "center",
        marginTop: { xs: 2, sm: 0 },
      }}
    >
      <Tooltip title={<span style={{ whiteSpace: "pre-line" }}>{getDetailedBuildInfo()}</span>} placement="top">
        <Typography
          variant="caption"
          sx={{
            color: "rgba(255, 255, 255, 0.7)",
            cursor: "help",
            fontFamily: "monospace",
            fontSize: "0.7rem",
          }}
        >
          🔧 DEV | {getVersionString()} | Built: {getShortBuildTime()}
        </Typography>
      </Tooltip>
    </Box>
  );
};
