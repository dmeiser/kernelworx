/**
 * SharedCampaignsPage Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MockedProvider } from "@apollo/client/testing/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { SharedCampaignsPage } from "../src/pages/SharedCampaignsPage";
import QRCode from "qrcode";
import {
  LIST_MY_SHARED_CAMPAIGNS,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  DELETE_SHARED_CAMPAIGN,
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

const mockSharedCampaigns = [
  {
    __typename: "SharedCampaign",
    sharedCampaignCode: "PACK123F25",
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
    __typename: "SharedCampaign",
    sharedCampaignCode: "TROOP456S25",
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
      query: LIST_MANAGED_CATALOGS,
    },
    result: {
      data: {
        listManagedCatalogs: [
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

const createListMock = (sharedCampaigns = mockSharedCampaigns) => ({
  request: {
    query: LIST_MY_SHARED_CAMPAIGNS,
  },
  result: {
    data: {
      listMySharedCampaigns: sharedCampaigns,
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

    it("displays shared campaigns in table after loading", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      expect(screen.getByText("Fall 2025")).toBeInTheDocument();
      expect(screen.getByText("Pack 123")).toBeInTheDocument();
      // Both shared campaigns use the same catalog, so there are multiple elements
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

    it("shows empty state when no shared campaigns exist", async () => {
      renderWithProviders([createListMock([])]);

      await waitFor(() => {
        expect(screen.getByText("No Shared Campaigns Yet")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/Create a shared campaign to generate shareable links/)
      ).toBeInTheDocument();
    });

    it("shows shared campaign count in header", async () => {
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
    it("opens QR dialog and downloads QR code when button clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByLabelText("View QR code");
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Campaign QR Code/)).toBeInTheDocument();
      });

      expect(screen.getByAltText("QR Code")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /download/i }));

      await waitFor(() => {
        expect(screen.getByText("QR code downloaded!")).toBeInTheDocument();
      });
    });

    it("shows error when QR generation fails", async () => {
      // Override mocked QRCode to reject
      const orig = (QRCode as any).toDataURL;
      (QRCode as any).toDataURL = vi.fn().mockRejectedValue(new Error("QR failed"));

      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      fireEvent.click(screen.getAllByLabelText("View QR code")[0]);

      await waitFor(() => {
        expect(screen.getByText("Failed to generate QR code")).toBeInTheDocument();
      });

      // restore
      (QRCode as any).toDataURL = orig;
    });
  });

  describe("Create button", () => {
    it("navigates to create page when Create Shared Campaign button clicked", async () => {
      const mocks = [...baseMocks(), createListMock()];

      render(
        <MockedProvider mocks={mocks}>
          <MemoryRouter initialEntries={["/shared-campaigns"]}>
            <Routes>
              <Route path="/shared-campaigns" element={<SharedCampaignsPage />} />
              <Route path="/shared-campaigns/create" element={<div>CREATE PAGE</div>} />
            </Routes>
          </MemoryRouter>
        </MockedProvider>
      );

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: /create shared campaign/i }));

      await waitFor(() => {
        expect(screen.getByText("CREATE PAGE")).toBeInTheDocument();
      });
    });

    it("disables create button when at 50 shared campaigns", { timeout: 20000 }, async () => {
      const many = new Array(50).fill(0).map((_, i) => ({
        __typename: "SharedCampaign",
        sharedCampaignCode: `CODE${i}`,
        catalogId: "catalog-1",
        catalog: { __typename: "Catalog", catalogId: "catalog-1", catalogName: "Official Popcorn 2025" },
        campaignName: "Fall",
        campaignYear: 2025,
        startDate: null,
        endDate: null,
        unitType: "Pack",
        unitNumber: i + 1,
        city: "Town",
        state: "ST",
        createdBy: "account-1",
        createdByName: "John Leader",
        creatorMessage: null,
        description: null,
        isActive: true,
        createdAt: new Date().toISOString(),
      }));

      renderWithProviders([createListMock(many)]);

      // The full-suite runs can be slower; instead of waiting for a specific code row, assert the create button disables reliably
      await waitFor(() => {
        const createButton = screen.getByRole("button", { name: /create shared campaign/i });
        expect(createButton).toBeDisabled();
      }, { timeout: 10000 });

      // Also assert header shows 50/50 active to be explicit
      await waitFor(() => expect(screen.getByText(/50\/50 active/)).toBeInTheDocument(), { timeout: 10000 });
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
          screen.getByText("Deactivate Campaign SharedCampaign?")
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
          screen.getByText("Deactivate Campaign SharedCampaign?")
        ).toBeInTheDocument();
      });

      const cancelButton = screen.getByRole("button", { name: "Cancel" });
      fireEvent.click(cancelButton);

      await waitFor(() => {
        expect(
          screen.queryByText("Deactivate Campaign SharedCampaign?")
        ).not.toBeInTheDocument();
      });
    });

    it("does not show deactivate button for inactive shared campaigns", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("TROOP456S25")).toBeInTheDocument();
      });

      // There should only be one deactivate button (for the active sharedCampaign)
      const deactivateButtons = screen.getAllByLabelText("Deactivate");
      expect(deactivateButtons).toHaveLength(1);
    });

    it("confirms deactivate and calls delete mutation", async () => {
      const deleteMock = {
        request: {
          query: DELETE_SHARED_CAMPAIGN,
          variables: { sharedCampaignCode: "PACK123F25" },
        },
        result: {
          data: { deleteSharedCampaign: true },
        },
      };

      // Provide an extra list mock to satisfy the refetch after deletion
      renderWithProviders([createListMock(), createListMock(), deleteMock]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const deactivateButtons = screen.getAllByLabelText("Deactivate");
      fireEvent.click(deactivateButtons[0]);

      await waitFor(() => {
        expect(
          screen.getByText("Deactivate Campaign SharedCampaign?")
        ).toBeInTheDocument();
      });

      const deactivateButton = screen.getByRole("button", { name: "Deactivate" });
      fireEvent.click(deactivateButton);

      await waitFor(() => {
        expect(screen.getByText("Shared Campaign deactivated")).toBeInTheDocument();
      });
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
        expect(screen.getByText("Edit Campaign SharedCampaign")).toBeInTheDocument();
      });

      // Should show read-only info
      expect(screen.getByText("Campaign Details (Read-Only)")).toBeInTheDocument();
    });

    it("closes edit dialog when cancel button clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const editButtons = screen.getAllByLabelText("Edit");
      fireEvent.click(editButtons[0]);

      await waitFor(() => {
        expect(screen.getByText("Edit Campaign SharedCampaign")).toBeInTheDocument();
      });

      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      fireEvent.click(cancelButton);

      await waitFor(() => {
        expect(screen.queryByText("Edit Campaign SharedCampaign")).not.toBeInTheDocument();
      });
    });
  });

  describe("QR dialog", () => {
    it("closes QR dialog when close button clicked", async () => {
      renderWithProviders([createListMock()]);

      await waitFor(() => {
        expect(screen.getByText("PACK123F25")).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByLabelText("View QR code");
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Campaign QR Code/)).toBeInTheDocument();
      });

      const closeButton = screen.getByRole("button", { name: /close/i });
      fireEvent.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText(/Campaign QR Code/)).not.toBeInTheDocument();
      });
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
