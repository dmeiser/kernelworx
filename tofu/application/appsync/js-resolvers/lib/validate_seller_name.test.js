import { describe, it } from 'node:test';
import assert from 'node:assert';
import { validateSellerName } from './validate_seller_name.js';

describe('validateSellerName', () => {
    it('rejects missing sellerName', () => {
        assert.throws(
            () => validateSellerName(undefined),
            /INVALID_INPUT: sellerName is required/
        );
    });

    it('rejects null sellerName', () => {
        assert.throws(
            () => validateSellerName(null),
            /INVALID_INPUT: sellerName is required/
        );
    });

    it('rejects empty string sellerName', () => {
        assert.throws(
            () => validateSellerName(''),
            /INVALID_INPUT: sellerName is required/
        );
    });

    it('rejects whitespace-only sellerName', () => {
        assert.throws(
            () => validateSellerName('   '),
            /INVALID_INPUT: sellerName is required/
        );
    });

    it('rejects sellerName exceeding 100 characters', () => {
        assert.throws(
            () => validateSellerName('A'.repeat(101)),
            /INVALID_INPUT: sellerName cannot exceed 100 characters/
        );
    });

    it('accepts sellerName of exactly 100 characters', () => {
        assert.strictEqual(validateSellerName('A'.repeat(100)), 'A'.repeat(100));
    });

    it('trims surrounding whitespace and returns the trimmed name', () => {
        assert.strictEqual(validateSellerName('  Scout Troop 100  '), 'Scout Troop 100');
    });
});
