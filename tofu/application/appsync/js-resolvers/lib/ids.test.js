import { describe, it } from 'node:test';
import assert from 'node:assert';
import { normalizeId, normalizeIdOrPrefix, stripIdPrefix, parseEmbeddedCampaignId, buildOrderId } from './ids.js';

describe('normalizeId', () => {
    it('prepends prefix when missing', () => {
        assert.strictEqual(normalizeId('123', 'PROFILE#'), 'PROFILE#123');
        assert.strictEqual(normalizeId('abc', 'ACCOUNT#'), 'ACCOUNT#abc');
        assert.strictEqual(normalizeId('xyz', 'CATALOG#'), 'CATALOG#xyz');
    });

    it('preserves prefix when already present', () => {
        assert.strictEqual(normalizeId('PROFILE#123', 'PROFILE#'), 'PROFILE#123');
        assert.strictEqual(normalizeId('ACCOUNT#abc', 'ACCOUNT#'), 'ACCOUNT#abc');
    });

    it('returns null for falsy or non-string values', () => {
        assert.strictEqual(normalizeId(null, 'PROFILE#'), null);
        assert.strictEqual(normalizeId('', 'PROFILE#'), null);
        assert.strictEqual(normalizeId(undefined, 'PROFILE#'), null);
        assert.strictEqual(normalizeId(123, 'PROFILE#'), null);
    });
});

describe('stripIdPrefix', () => {
    it('strips prefix when present', () => {
        assert.strictEqual(stripIdPrefix('ACCOUNT#123', 'ACCOUNT#'), '123');
        assert.strictEqual(stripIdPrefix('PROFILE#abc', 'PROFILE#'), 'abc');
        assert.strictEqual(stripIdPrefix('CAMPAIGN#xyz', 'CAMPAIGN#'), 'xyz');
    });

    it('leaves value unchanged when prefix is not present', () => {
        assert.strictEqual(stripIdPrefix('123', 'ACCOUNT#'), '123');
        assert.strictEqual(stripIdPrefix('abc', 'PROFILE#'), 'abc');
    });

    it('returns original value for non-string or falsy values', () => {
        assert.strictEqual(stripIdPrefix(null, 'ACCOUNT#'), null);
        assert.strictEqual(stripIdPrefix(undefined, 'ACCOUNT#'), undefined);
        assert.strictEqual(stripIdPrefix('', 'ACCOUNT#'), '');
        assert.strictEqual(stripIdPrefix(123, 'ACCOUNT#'), 123);
    });
});

describe('normalizeIdOrPrefix', () => {
    it('behaves like normalizeId for a real value', () => {
        assert.strictEqual(normalizeIdOrPrefix('123', 'PROFILE#'), 'PROFILE#123');
        assert.strictEqual(normalizeIdOrPrefix('PROFILE#123', 'PROFILE#'), 'PROFILE#123');
    });

    it('falls back to a bare prefix so a key attribute is never null', () => {
        assert.strictEqual(normalizeIdOrPrefix(null, 'ACCOUNT#'), 'ACCOUNT#');
        assert.strictEqual(normalizeIdOrPrefix('', 'ACCOUNT#'), 'ACCOUNT#');
        assert.strictEqual(normalizeIdOrPrefix(undefined, 'ACCOUNT#'), 'ACCOUNT#');
        assert.strictEqual(normalizeIdOrPrefix(123, 'ACCOUNT#'), 'ACCOUNT#');
    });
});

describe('buildOrderId', () => {
    it('round-trips through parseEmbeddedCampaignId', () => {
        const orderId = buildOrderId('CAMPAIGN#campaign-123', '550e8400-e29b-41d4-a716-446655440000');

        assert.strictEqual(orderId, 'ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000');
        assert.strictEqual(parseEmbeddedCampaignId(orderId), 'CAMPAIGN#campaign-123');
    });

    it('does not double the campaign prefix when one is already stripped', () => {
        assert.strictEqual(
            buildOrderId('campaign-123', 'suffix-1'),
            buildOrderId('CAMPAIGN#campaign-123', 'suffix-1')
        );
    });
});

describe('parseEmbeddedCampaignId', () => {
    it('extracts and normalizes campaignId from orderId with embedded campaign', () => {
        assert.strictEqual(
            parseEmbeddedCampaignId('ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000'),
            'CAMPAIGN#campaign-123'
        );
    });

    it('returns null for legacy order IDs without embedded campaign', () => {
        assert.strictEqual(
            parseEmbeddedCampaignId('ORDER#550e8400-e29b-41d4-a716-446655440000'),
            null
        );
    });

    it('returns null for invalid or non-string inputs', () => {
        assert.strictEqual(parseEmbeddedCampaignId(null), null);
        assert.strictEqual(parseEmbeddedCampaignId(undefined), null);
        assert.strictEqual(parseEmbeddedCampaignId(''), null);
        assert.strictEqual(parseEmbeddedCampaignId('NOTANORDER#123#456'), null);
        assert.strictEqual(parseEmbeddedCampaignId('ORDER#onlyonepart'), null);
        assert.strictEqual(parseEmbeddedCampaignId('ORDER#part1#part2#part3'), null);
    });
});
