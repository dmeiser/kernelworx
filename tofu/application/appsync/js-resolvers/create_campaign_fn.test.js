import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_campaign_fn.js';

describe('create_campaign_fn request', () => {
    const baseInput = {
        profileId: '11111111-1111-1111-1111-111111111111',
        campaignName: 'Popcorn Sale',
        campaignYear: 2025,
        catalogId: '22222222-2222-2222-2222-222222222222',
        startDate: '2025-09-01T00:00:00Z',
    };

    const baseCtx = {
        args: { input: baseInput },
        stash: {
            profile: {
                profileId: 'PROFILE#11111111-1111-1111-1111-111111111111',
                ownerAccountId: 'ACCOUNT#owner-1',
            },
        },
        identity: { sub: 'owner-1' },
    };

    it('creates campaign with basic required fields', () => {
        const result = request(baseCtx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#11111111-1111-1111-1111-111111111111');
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#auto-generated-id');
        assert.strictEqual(result.attributeValues.campaignName, 'Popcorn Sale');
        assert.strictEqual(result.attributeValues.campaignYear, 2025);
        assert.strictEqual(result.attributeValues.catalogId, 'CATALOG#22222222-2222-2222-2222-222222222222');
        assert.strictEqual(result.attributeValues.startDate, '2025-09-01T00:00:00Z');
        assert.strictEqual(result.attributeValues.isActive, true);
        assert.strictEqual(result.attributeValues.createdAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(result.attributeValues.updatedAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(result.condition.expression, 'attribute_not_exists(campaignId)');
        assert.strictEqual(baseCtx.stash.createdCampaign, result.attributeValues);
    });

    it('does not double prefix profileId or catalogId when already prefixed', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    profileId: 'PROFILE#custom-profile-id',
                    catalogId: 'CATALOG#custom-catalog-id',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.key.profileId, 'PROFILE#custom-profile-id');
        assert.strictEqual(result.attributeValues.catalogId, 'CATALOG#custom-catalog-id');
    });

    it('creates unitCampaignKey when unit fields are provided', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    unitNumber: 42,
                    city: 'Springfield',
                    state: 'IL',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.attributeValues.unitType, 'Pack');
        assert.strictEqual(result.attributeValues.unitNumber, 42);
        assert.strictEqual(result.attributeValues.city, 'Springfield');
        assert.strictEqual(result.attributeValues.state, 'IL');
        assert.strictEqual(result.attributeValues.unitCampaignKey, 'Pack#42#Springfield#IL#Popcorn Sale#2025');
    });

    it('coerces string unitNumber and positive float to integer', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Troop',
                    unitNumber: '100',
                    city: 'Chicago',
                    state: 'IL',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.attributeValues.unitNumber, 100);
        assert.strictEqual(result.attributeValues.unitCampaignKey, 'Troop#100#Chicago#IL#Popcorn Sale#2025');
    });

    it('rejects unitNumber when unitType is provided but unitNumber is missing', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    city: 'Springfield',
                    state: 'IL',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitNumber is required when unitType is provided/
        );
    });

    it('rejects invalid unitNumber format', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    unitNumber: 'not-a-number',
                    city: 'Springfield',
                    state: 'IL',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitNumber must be a valid integer/
        );
    });

    it('rejects non-positive unitNumber', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    unitNumber: 0,
                    city: 'Springfield',
                    state: 'IL',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitNumber must be a positive integer/
        );
    });

    it('rejects missing city when unitType is provided', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    unitNumber: 10,
                    state: 'IL',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: city is required when unitType is provided/
        );
    });

    it('rejects missing state when unitType is provided', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitType: 'Pack',
                    unitNumber: 10,
                    city: 'Springfield',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: state is required when unitType is provided/
        );
    });

    it('rejects unit fields when unitType is missing', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    unitNumber: 10,
                    city: 'Springfield',
                    state: 'IL',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitType is required when unit fields are present/
        );
    });

    it('rejects missing campaignName', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    campaignName: '',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: campaign_name is required/
        );
    });

    it('rejects missing campaignYear', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    campaignYear: null,
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: campaign_year is required/
        );
    });

    it('rejects non-integer campaignYear', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    campaignYear: 'invalid-year',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: campaign_year must be a valid integer/
        );
    });

    it('rejects missing catalogId', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    catalogId: '',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: catalog_id is required/
        );
    });

    it('accepts valid endDate after startDate', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    startDate: '2025-01-01T00:00:00Z',
                    endDate: '2025-12-31T23:59:59Z',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.attributeValues.startDate, '2025-01-01T00:00:00Z');
        assert.strictEqual(result.attributeValues.endDate, '2025-12-31T23:59:59Z');
    });

    it('rejects endDate equal to or before startDate', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    startDate: '2025-12-31T00:00:00Z',
                    endDate: '2025-01-01T00:00:00Z',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: endDate must be after startDate/
        );
    });

    it('rejects invalid date format', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    startDate: 'not-a-date',
                    endDate: '2025-01-01T00:00:00Z',
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Invalid date format for startDate or endDate/
        );
    });

    it('rejects non-string date', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    startDate: 12345,
                },
            },
            stash: {},
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Invalid date format for startDate or endDate/
        );
    });

    it('accepts mixed timezone-aware and naive dates', () => {
        const ctx = {
            args: {
                input: {
                    ...baseInput,
                    startDate: '2025-01-01T00:00:00',
                    endDate: '2025-12-31T00:00:00Z',
                },
            },
            stash: {},
        };

        const result = request(ctx);
        assert.strictEqual(result.attributeValues.startDate, '2025-01-01T00:00:00');
        assert.strictEqual(result.attributeValues.endDate, '2025-12-31T00:00:00Z');
    });

    it('merges values from shared campaign when present', () => {
        const sharedCampaign = {
            sharedCampaignCode: 'SHARED-123',
            campaignName: 'Shared Fall Fundraiser',
            campaignYear: 2026,
            catalogId: 'CATALOG#shared-cat-1',
            unitType: 'Crew',
            unitNumber: 77,
            city: 'Peoria',
            state: 'IL',
            startDate: '2026-08-01T00:00:00Z',
            endDate: '2026-11-01T00:00:00Z',
        };

        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#my-profile',
                    sharedCampaignCode: '  SHARED-123  ',
                    // Override startDate only
                    startDate: '2026-08-15T00:00:00Z',
                },
            },
            stash: {
                sharedCampaign,
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.attributeValues.campaignName, 'Shared Fall Fundraiser');
        assert.strictEqual(result.attributeValues.campaignYear, 2026);
        assert.strictEqual(result.attributeValues.catalogId, 'CATALOG#shared-cat-1');
        assert.strictEqual(result.attributeValues.unitType, 'Crew');
        assert.strictEqual(result.attributeValues.unitNumber, 77);
        assert.strictEqual(result.attributeValues.city, 'Peoria');
        assert.strictEqual(result.attributeValues.state, 'IL');
        assert.strictEqual(result.attributeValues.startDate, '2026-08-15T00:00:00Z'); // Overridden
        assert.strictEqual(result.attributeValues.endDate, '2026-11-01T00:00:00Z'); // Kept from shared
        assert.strictEqual(result.attributeValues.sharedCampaignCode, 'SHARED-123'); // Trimmed from stash
        assert.strictEqual(result.attributeValues.unitCampaignKey, 'Crew#77#Peoria#IL#Shared Fall Fundraiser#2026');
    });
});

describe('create_campaign_fn response', () => {
    it('returns stashed created campaign item', () => {
        const campaignItem = {
            campaignId: 'CAMPAIGN#123',
            campaignName: 'Test',
        };
        const ctx = {
            stash: { createdCampaign: campaignItem },
        };

        const result = response(ctx);
        assert.deepStrictEqual(result, campaignItem);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'PutItem failed', type: 'DynamoDB:InternalServerError' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: PutItem failed/
        );
    });
});
