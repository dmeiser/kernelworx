/**
 * SharedCampaignsPage Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MockedProvider } from "@apollo/client/testing/react";
import { MemoryRouter } from "react-router-dom";
import { SharedCampaignsPage } from "../src/pages/SharedCampaignsPage";
import {
  LIST_MY_SHARED_CAMPAIGNS,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
} from "../src/lib/graphql";

// Mock QRCode
vi.mock("qrcode", () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,mockqrcode"),
  },
}));

// Mock clipboard API
Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn().mockResolvedValue(undefined),
  },
});

const mockPrefills = [
  {
    __typename: "CampaignPrefill",
    prefillCode: "PACK123F25",
    catalogId: "catalog-1",
    catalog: {
      __typename: "Catalog",
      catalogId: "catalog-1",
      catalogName: "Official Popcorn 2025",
    },
    campaignName: "Fall",
    campaignYear: 2025,
    startDate: "2025-09-01",
    endDate: "2025-12-01",
    unitType: "Pack",
    unitNumber: 123,
    city: "Springfield",
    state: "IL",
    createdBy: "account-1",
    createdByName: "John Leader",
    creatorMessage: "Join our pack's sale!",
    description: "Fall 2025 campaign for Pack 123",
    isActive: true,
    createdAt: "2025-01-15T00:00:00.000Z",
  },
  {
    __typename: "CampaignPrefill",
    prefillCode: "TROOP456S25",
    catalogId: "catalog-1",
    catalog: {
      __typename: "Catalog",
      catalogId: "catalog-1",
      catalogName: "Official Popcorn 2025",
    },
    campaignName: "Spring",
    campaignYear: 2025,
    startDate: null,
    endDate: null,
    unitType: "Troop",
    unitNumber: 456,
    city: "Chicago",
    state: "IL",
    createdBy: "account-1",
    createdByName: "John Leader",
    creatorMessage: null,
    description: null,
    isActive: false,
    createdAt: "2025-01-10T00:00:00.000Z",
  },
];

// Base mocks that should be included in all tests
const baseMocks = () => [
  {
    request: {
      query: LIST_PUBLIC_CATALOGS,
    },
    result: {
      data: {
        listPublicCatalogs: [
          { catalogId: "catalog-1", catalogName: "Official Popcorn 2025", catalogType: "ADMIN_MANAGED" },
        ],
      },
    },
  },
  {
    request: {
      query: LIST_MY_CATALOGS,
    },
    result: {
      data: {
        listMyCatalogs: [],
      },
    },
  },
];

const createListMock = (prefills = mockPrefills) => ({
  request: {
    query: LIST_MY_SHARED_CAMPAIGNS,
  },
  result: {
    data: {
      listMyCampaignPrefills: prefills,
    },
  },
});

const renderWithProviders = (mocks: any[]) => {
  // Always include base mocks for catalog queries triggered by CreateSharedCampaignDialog
  const allMocks = [...baseMocks(), ...mocks];
  return render(
    <MockedProvider mocks={allMocks}>
      <MemoryRouter>
        <SharedCampaignsPage />
      </MemoryRouter>
    </MockedProvider>
  );
};

describe("SharedCampaignsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("List display", () => {
    it("shows loading state initially", () => {
      renderWithProviders([createListMock()]);
      expect(screen.getByRole("progressbar")).toBeInTheDocument();
    });

    it("displays prefills in table after loading", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      expect(screen.getByText("Fall 2025")).toBeInTheDocument();
      expect(screen.getByText("Pack 123")).toBeInTheDocument();
      // Both prefills use the same catalog, so there are multiple elements
      expect(screen.getAllByText("Official Popcorn 2025")).toHaveLength(2);
    });

    it("shows active and inactive status chips", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });

    it("shows empty state when no prefills exist", async () => {
      renderWithProviders([createListMock([])]);

      await waitFor(() => {
        expect(screen.getByText("No Shared Campaigns Yet")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/Create a shared campaign to generate shareable links/)
      ).toBeInTheDocument();
    });

    it("shows prefill count in header", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText(/1\/50 active/)).toBeInTheDocument();
      });
    });
  });

  describe("Copy link functionality", () => {
    it("copies link to clipboard when copy button clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const copyButtons = screen.getAllByLabelText("Copy link");
      fireEvent.click(copyButtons[0]);

      await waitFor(() => {
        expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
          expect.stringContaining("/c/PACK123F25")
        );
      });
    });
  });

  describe("QR code download", () => {
    it.skip("downloads QR code when button clicked", async () => {
      // TODO: This test needs to be rewritten to match actual QR download behavior
      // which uses dialog + button, not direct click
    });
  });

  describe("Create button", () => {
    it.skip("navigates to create page when Create Shared Campaign button clicked", async () => {
      // TODO: Test navigation to /shared-campaigns/create
      // This test needs to check that the button navigates, not that a dialog opens
    });

    it.skip("disables create button when at 50 prefills", async () => {
      // TODO: Test that button is disabled when at max prefills
    });
  });

  describe("Deactivate dialog", () => {
    it("opens deactivate confirmation when deactivate clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const deactivateButtons = screen.getAllByLabelText("Deactivate");
      fireEvent.click(deactivateButtons[0]);

      await waitFor(() => {
        expect(
          screen.getByText("Deactivate Campaign Prefill?")
        ).toBeInTheDocument();
      });

      expect(
        screen.getByText(/The link will no longer work for new campaign creation/)
      ).toBeInTheDocument();
    });

    it("closes deactivate dialog when cancel clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const deactivateButtons = screen.getAllByLabelText("Deactivate");
      fireEvent.click(deactivateButtons[0]);

      await waitFor(() => {
        expect(
          screen.getByText("Deactivate Campaign Prefill?")
        ).toBeInTheDocument();
      });

      const cancelButton = screen.getByRole("button", { name: "Cancel" });
      fireEvent.click(cancelButton);

      await waitFor(() => {
        expect(
          screen.queryByText("Deactivate Campaign Prefill?")
        ).not.toBeInTheDocument();
      });
    });

    it("does not show deactivate button for inactive prefills", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("TROOP456S25")).toBeInTheDocument();
      });

      // There should only be one deactivate button (for the active prefill)
      const deactivateButtons = screen.getAllByLabelText("Deactivate");
      expect(deactivateButtons).toHaveLength(1);
    });
  });

  describe("Edit dialog", () => {
    it("opens edit dialog when edit button clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const editButtons = screen.getAllByLabelText("Edit");
      fireEvent.click(editButtons[0]);

      await waitFor(() => {
        expect(screen.getByText("Edit Campaign Prefill")).toBeInTheDocument();
      });

      // Should show read-only info
      expect(screen.getByText("Campaign Details (Read-Only)")).toBeInTheDocument();
    });
  });

  describe("Error handling", () => {
    it("displays error message when query fails", async () => {
      const errorMock = {
        request: {
          query: LIST_MY_SHARED_CAMPAIGNS,
        },
        error: new Error("Network error"),
      };

      renderWithProviders([errorMock]);

      await waitFor(() => {
        expect(screen.getByText(/Failed to load shared campaigns/)).toBeInTheDocument();
      });
    });
  });
});
