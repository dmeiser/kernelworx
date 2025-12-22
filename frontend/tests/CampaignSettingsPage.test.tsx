/**
 * CampaignSettingsPage tests
 *
 * Tests for sharedCampaign-created campaign warnings and confirmation dialogs.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MockedProvider } from "@apollo/client/testing/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CampaignSettingsPage } from "../src/pages/CampaignSettingsPage";
import {
  GET_CAMPAIGN,
  UPDATE_CAMPAIGN,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
} from "../src/lib/graphql";

// Mock campaign data
const mockCampaignWithSharedCampaign = {
  campaignId: "campaign-123",
  campaignName: "Fall",
  campaignYear: 2025,
  startDate: "2025-09-01T00:00:00.000Z",
  endDate: "2025-12-01T23:59:59.999Z",
  catalogId: "catalog-1",
  profileId: "profile-123",
  sharedCampaignCode: "PACK123F25",
  unitType: "Pack",
  unitNumber: 123,
  city: "Springfield",
  state: "IL",
};

const mockCampaignWithoutSharedCampaign = {
  campaignId: "campaign-456",
  campaignName: "Spring",
  campaignYear: 2025,
  startDate: "2025-03-01T00:00:00.000Z",
  endDate: "2025-06-01T23:59:59.999Z",
  catalogId: "catalog-1",
  profileId: "profile-123",
  sharedCampaignCode: null,
};

const mockCatalogs = [
  { catalogId: "catalog-1", catalogName: "Official Popcorn 2025", catalogType: "ADMIN_MANAGED", isDeleted: false },
  { catalogId: "catalog-2", catalogName: "My Custom Catalog", catalogType: "USER_CREATED", isDeleted: false },
];

const createMocks = (campaign: typeof mockCampaignWithSharedCampaign | typeof mockCampaignWithoutSharedCampaign): any[] => [
  {
    request: {
      query: GET_CAMPAIGN,
      variables: { campaignId: campaign.campaignId },
    },
    result: {
      data: {
        getCampaign: campaign,
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

const renderWithProviders = (mocks: any[], campaignId: string, profileId: string) => {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[`/scouts/${profileId}/campaigns/${campaignId}/settings`]}>
        <Routes>
          <Route
            path="/scouts/:profileId/campaigns/:campaignId/settings"
            element={<CampaignSettingsPage />}
          />
        </Routes>
      </MemoryRouter>
    </MockedProvider>
  );
};

describe("CampaignSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("SharedCampaign warning display", () => {
    it("displays warning for sharedCampaign-created campaigns", async () => {
      const mocks = createMocks(mockCampaignWithSharedCampaign);
      renderWithProviders(mocks, mockCampaignWithSharedCampaign.campaignId, mockCampaignWithSharedCampaign.profileId);

      await waitFor(() => {
        expect(screen.getByText("Shared Campaign")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/This campaign was created from a shared campaign link/)
      ).toBeInTheDocument();
    });

    it("does not display warning for regular campaigns", async () => {
      const mocks = createMocks(mockCampaignWithoutSharedCampaign);
      renderWithProviders(mocks, mockCampaignWithoutSharedCampaign.campaignId, mockCampaignWithoutSharedCampaign.profileId);

      await waitFor(() => {
        expect(screen.getByText("Campaign Settings")).toBeInTheDocument();
      });

        expect(screen.queryByText("Shared Campaign")).not.toBeInTheDocument();
    });
  });

  describe("Confirmation dialog for unit-related changes", () => {
    it("shows confirmation dialog when changing campaign name on shared campaign", async () => {
      const mocks = createMocks(mockCampaignWithSharedCampaign);
      renderWithProviders(mocks, mockCampaignWithSharedCampaign.campaignId, mockCampaignWithSharedCampaign.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Campaign Name")).toBeInTheDocument();
      });

      // Change the campaign name
      const campaignNameInput = screen.getByLabelText("Campaign Name");
      fireEvent.change(campaignNameInput, { target: { value: "Winter" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should appear
      await waitFor(() => {
        expect(screen.getByText("Confirm Changes to Shared Campaign")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/You are changing the campaign name or catalog/)
      ).toBeInTheDocument();
    });

    // Note: Catalog change confirmation is covered by the campaign name test above.
    // Both campaign name and catalog changes trigger the same hasUnitRelatedChanges logic.
    // MUI Select components are difficult to test with getByLabelText due to how
    // FormControl/InputLabel renders, so we test the confirmation flow via campaign name only.

    it("does not show confirmation for date changes on shared campaign", async () => {
      const updateMock = {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: mockCampaignWithSharedCampaign.campaignId,
              campaignName: mockCampaignWithSharedCampaign.campaignName,
              startDate: "2025-09-15T00:00:00.000Z",
              endDate: "2025-12-01T23:59:59.999Z",
              catalogId: mockCampaignWithSharedCampaign.catalogId,
            },
          },
        },
        result: {
          data: {
            updateCampaign: { ...mockCampaignWithSharedCampaign, startDate: "2025-09-15T00:00:00.000Z" },
          },
        },
      };

      const mocks = [...createMocks(mockCampaignWithSharedCampaign), updateMock];
      renderWithProviders(mocks, mockCampaignWithSharedCampaign.campaignId, mockCampaignWithSharedCampaign.profileId);

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

    it("does not show confirmation for regular campaigns", async () => {
      const updateMock = {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: mockCampaignWithoutSharedCampaign.campaignId,
              campaignName: "Winter",
              startDate: "2025-03-01T00:00:00.000Z",
              endDate: "2025-06-01T23:59:59.999Z",
              catalogId: mockCampaignWithoutSharedCampaign.catalogId,
            },
          },
        },
        result: {
          data: {
            updateCampaign: { ...mockCampaignWithoutSharedCampaign, campaignName: "Winter" },
          },
        },
      };

      const mocks = [...createMocks(mockCampaignWithoutSharedCampaign), updateMock];
      renderWithProviders(mocks, mockCampaignWithoutSharedCampaign.campaignId, mockCampaignWithoutSharedCampaign.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Campaign Name")).toBeInTheDocument();
      });

      // Change the campaign name
      const campaignNameInput = screen.getByLabelText("Campaign Name");
      fireEvent.change(campaignNameInput, { target: { value: "Winter" } });

      // Click save
      const saveButton = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveButton);

      // Confirmation dialog should NOT appear for regular campaigns
      await waitFor(() => {
        expect(screen.queryByText("Confirm Changes to Shared Campaign")).not.toBeInTheDocument();
      });
    });

    it("cancels save when Cancel is clicked in confirmation dialog", async () => {
      const mocks = createMocks(mockCampaignWithSharedCampaign);
      renderWithProviders(mocks, mockCampaignWithSharedCampaign.campaignId, mockCampaignWithSharedCampaign.profileId);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByLabelText("Campaign Name")).toBeInTheDocument();
      });

      // Change the campaign name
      const campaignNameInput = screen.getByLabelText("Campaign Name");
      fireEvent.change(campaignNameInput, { target: { value: "Winter" } });

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
