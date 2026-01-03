import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MockedProvider } from "@apollo/client/testing/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { CampaignSettingsPage } from "../src/pages/CampaignSettingsPage";
import { GET_CAMPAIGN, LIST_PUBLIC_CATALOGS, LIST_MY_CATALOGS } from "../src/lib/graphql";

const mockCampaign = {
  campaignId: "campaign-123",
  campaignName: "Fall",
  campaignYear: 2025,
  startDate: "2025-09-01T00:00:00.000Z",
  endDate: "2025-12-01T23:59:59.999Z",
  catalogId: "catalog-1",
  profileId: "profile-123",
  sharedCampaignCode: "PACK123F25",
};

const mockCatalogs = [
  { catalogId: "catalog-1", catalogName: "Official", catalogType: "ADMIN_MANAGED", isDeleted: false },
];

const createMocks = () => {
  const dbCampaignId = `CAMPAIGN#${mockCampaign.campaignId}`;
  const dbProfileId = `PROFILE#${mockCampaign.profileId}`;
  return [
    {
      request: { query: GET_CAMPAIGN, variables: { campaignId: dbCampaignId } },
      result: { data: { getCampaign: { ...mockCampaign, campaignId: dbCampaignId, profileId: dbProfileId, catalogId: mockCampaign.catalogId, catalog: { catalogId: mockCatalogs[0].catalogId, catalogName: mockCatalogs[0].catalogName, catalogType: mockCatalogs[0].catalogType, isDeleted: mockCatalogs[0].isDeleted } } } },
    },
    { request: { query: LIST_PUBLIC_CATALOGS }, result: { data: { listPublicCatalogs: mockCatalogs } } },
    { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [] } } },
  ];
};

const renderWithMocks = (mocks: any[]) =>
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[`/scouts/${mockCampaign.profileId}/campaigns/${mockCampaign.campaignId}/settings`]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/settings" element={<CampaignSettingsPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

describe("CampaignSettingsPage (core flows)", () => {
  it("shows Shared Campaign banner for shared campaigns", async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText("Shared Campaign")).toBeTruthy());
  });

  it("shows confirmation dialog when changing campaign name on shared campaign", async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText("Campaign Name")).toBeTruthy());

    const nameInput = screen.getByLabelText("Campaign Name");
    fireEvent.change(nameInput, { target: { value: "Winter" } });

    const save = screen.getByRole("button", { name: /save changes/i });
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText("Confirm Changes to Shared Campaign")).toBeTruthy());
  });
});