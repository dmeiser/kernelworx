import { describe, it, expect, vi } from 'vitest';
import { fetchAllMyProfiles } from '../../src/lib/myProfiles';

describe('fetchAllMyProfiles', () => {
  it('returns an empty list when the connection page is missing', async () => {
    const client = {
      query: vi.fn().mockResolvedValue({ data: {}, error: undefined }),
    } as any;

    await expect(fetchAllMyProfiles(client)).resolves.toEqual([]);
    expect(client.query).toHaveBeenCalledTimes(1);
  });

  it('accumulates pages until nextToken is exhausted', async () => {
    const client = {
      query: vi
        .fn()
        .mockResolvedValueOnce({
          data: {
            listMyProfiles: {
              profiles: [{ profileId: 'PROFILE#1' }],
              nextToken: 'next-1',
            },
          },
          error: undefined,
        })
        .mockResolvedValueOnce({
          data: {
            listMyProfiles: {
              profiles: [{ profileId: 'PROFILE#2' }],
              nextToken: null,
            },
          },
          error: undefined,
        }),
    } as any;

    await expect(fetchAllMyProfiles(client)).resolves.toEqual([
      { profileId: 'PROFILE#1' },
      { profileId: 'PROFILE#2' },
    ]);
    expect(client.query).toHaveBeenCalledTimes(2);
  });

  it('throws GraphQL errors instead of returning a partial list', async () => {
    const gqlError = new Error('boom');
    const client = {
      query: vi.fn().mockResolvedValue({ data: undefined, error: gqlError }),
    } as any;

    await expect(fetchAllMyProfiles(client)).rejects.toBe(gqlError);
  });
});
