import { describe, it } from 'node:test';
import assert from 'node:assert';
import { normalizeId, stripIdPrefix, parseEmbeddedCampaignId } from './ids.js';

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
