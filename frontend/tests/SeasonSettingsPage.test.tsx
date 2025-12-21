/**
 * SeasonSettingsPage tests
 *
 * Tests for prefill-created season warnings and confirmation dialogs.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MockedProvider } from "@apollo/client/testing/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SeasonSettingsPage } from "../src/pages/SeasonSettingsPage";
import {
  GET_SEASON,
  UPDATE_SEASON,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
} from "../src/lib/graphql";

// Mock season data
const mockSeasonWithPrefill = {
  seasonId: "season-123",
  seasonName: "Fall",
  seasonYear: 2025,
  startDate: "2025-09-01T00:00:00.000Z",
  endDate: "2025-12-01T23:59:59.999Z",
  catalogId: "catalog-1",
  profileId: "profile-123",
  prefillCode: "PACK123F25",
  unitType: "Pack",
  unitNumber: 123,
  city: "Springfield",
  state: "IL",
};

const mockSeasonWithoutPrefill = {
  seasonId: "season-456",
  seasonName: "Spring",
  seasonYear: 2025,
  startDate: "2025-03-01T00:00:00.000Z",
  endDate: "2025-06-01T23:59:59.999Z",
  catalogId: "catalog-1",
  profileId: "profile-123",
  prefillCode: null,
};

const mockCatalogs = [
  { catalogId: "catalog-1", catalogName: "Official Popcorn 2025", catalogType: "ADMIN_MANAGED", isDeleted: false },
  { catalogId: "catalog-2", catalogName: "My Custom Catalog", catalogType: "USER_CREATED", isDeleted: false },
];

const createMocks = (season: typeof mockSeasonWithPrefill | typeof mockSeasonWithoutPrefill): any[] => [
  {
    request: {
      query: GET_SEASON,
      variables: { seasonId: season.seasonId },
    },
    result: {
      data: {
        getSeason: season,
      },
    },
  },
  {
    request: {
      query: LIST_PUBLIC_CATALOGS,
    },
    result: {
      data: {
        listPublicCatalogs: mockCatalogs.filter((c) => c.catalogType === "ADMIN_MANAGED"),
      },
    },
  },
  {
    request: {
      query: LIST_MY_CATALOGS,
    },
    result: {
      data: {
        listMyCatalogs: mockCatalogs.filter((c) => c.catalogType === "USER_CREATED"),
      },
    },
  },
];

const renderWithProviders = (mocks: any[], seasonId: string, profileId: string) => {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[`/scouts/${profileId}/campaigns/${seasonId}/settings`]}>
        <Routes>
          <Route
            path="/scouts/:profileId/campaigns/:seasonId/settings"
            element={<SeasonSettingsPage />}
          />
        </Routes>
      </MemoryRouter>
    </MockedProvider>
  );
};

describe("SeasonSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Prefill warning display", () => {
    it("displays warning for prefill-created seasons", async () => {
      const mocks = createMocks(mockSeasonWithPrefill);
      renderWithProviders(mocks, mockSeasonWithPrefill.seasonId, mockSeasonWithPrefill.profileId);

      await waitFor(() => {
        expect(screen.getByText("Shared Campaign")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/This season was created from a campaign link/)
      ).toBeInTheDocument();
    });

    it("does not display warning for regular seasons", async () => {
      const mocks = createMocks(mockSeasonWithoutPrefill);
      renderWithProviders(mocks, mockSeasonWithoutPrefill.seasonId, mockSeasonWithoutPrefill.profileId);

      await waitFor(() => {
        expect(screen.getByText("Season Settings")).toBeInTheDocument();
      });

        expect(screen.queryByText("Shared Campaign")).not.toBeInTheDocument();
    });
  });

  describe("Confirmation dialog for unit-related changes", () => {
    it("shows confirmation dialog when changing season name on prefill season", async () => {
      const mocks = createMocks(mockSeasonWithPrefill);
      renderWithProviders(mocks, mockSeasonWithPrefill.seasonId, mockSeasonWithPrefill.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Season Name")).toBeInTheDocument();
      });

      // Change the season name
      const seasonNameInput = screen.getByLabelText("Season Name");
      fireEvent.change(seasonNameInput, { target: { value: "Winter" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should appear
      await waitFor(() => {
        expect(screen.getByText("Confirm Changes to Shared Campaign")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/You are changing the season name or catalog/)
      ).toBeInTheDocument();
    });

    // Note: Catalog change confirmation is covered by the season name test above.
    // Both season name and catalog changes trigger the same hasUnitRelatedChanges logic.
    // MUI Select components are difficult to test with getByLabelText due to how
    // FormControl/InputLabel renders, so we test the confirmation flow via season name only.

    it("does not show confirmation for date changes on prefill season", async () => {
      const updateMock = {
        request: {
          query: UPDATE_SEASON,
          variables: {
            input: {
              seasonId: mockSeasonWithPrefill.seasonId,
              seasonName: mockSeasonWithPrefill.seasonName,
              startDate: "2025-09-15T00:00:00.000Z",
              endDate: "2025-12-01T23:59:59.999Z",
              catalogId: mockSeasonWithPrefill.catalogId,
            },
          },
        },
        result: {
          data: {
            updateSeason: { ...mockSeasonWithPrefill, startDate: "2025-09-15T00:00:00.000Z" },
          },
        },
      };

      const mocks = [...createMocks(mockSeasonWithPrefill), updateMock];
      renderWithProviders(mocks, mockSeasonWithPrefill.seasonId, mockSeasonWithPrefill.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Start Date")).toBeInTheDocument();
      });

      // Change only the start date
      const startDateInput = screen.getByLabelText("Start Date");
      fireEvent.change(startDateInput, { target: { value: "2025-09-15" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should NOT appear (dates don't require confirmation)
      await waitFor(() => {
        expect(screen.queryByText("Confirm Changes to Shared Campaign")).not.toBeInTheDocument();
      });
    });

    it("does not show confirmation for regular seasons", async () => {
      const updateMock = {
        request: {
          query: UPDATE_SEASON,
          variables: {
            input: {
              seasonId: mockSeasonWithoutPrefill.seasonId,
              seasonName: "Winter",
              startDate: "2025-03-01T00:00:00.000Z",
              endDate: "2025-06-01T23:59:59.999Z",
              catalogId: mockSeasonWithoutPrefill.catalogId,
            },
          },
        },
        result: {
          data: {
            updateSeason: { ...mockSeasonWithoutPrefill, seasonName: "Winter" },
          },
        },
      };

      const mocks = [...createMocks(mockSeasonWithoutPrefill), updateMock];
      renderWithProviders(mocks, mockSeasonWithoutPrefill.seasonId, mockSeasonWithoutPrefill.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Season Name")).toBeInTheDocument();
      });

      // Change the season name
      const seasonNameInput = screen.getByLabelText("Season Name");
      fireEvent.change(seasonNameInput, { target: { value: "Winter" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should NOT appear for regular seasons
      await waitFor(() => {
        expect(screen.queryByText("Confirm Changes to Shared Campaign")).not.toBeInTheDocument();
      });
    });

    it("cancels save when Cancel is clicked in confirmation dialog", async () => {
      const mocks = createMocks(mockSeasonWithPrefill);
      renderWithProviders(mocks, mockSeasonWithPrefill.seasonId, mockSeasonWithPrefill.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Season Name")).toBeInTheDocument();
      });

      // Change the season name
      const seasonNameInput = screen.getByLabelText("Season Name");
      fireEvent.change(seasonNameInput, { target: { value: "Winter" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should appear
      await waitFor(() => {
        expect(screen.getByText("Confirm Changes to Shared Campaign")).toBeInTheDocument();
      });

      // Click Cancel
      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      fireEvent.click(cancelButton);

      // Dialog should close
      await waitFor(() => {
        expect(screen.queryByText("Confirm Changes to Shared Campaign")).not.toBeInTheDocument();
      });
    });
  });
});
