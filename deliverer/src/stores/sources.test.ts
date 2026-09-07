import type { SourcesStatus } from '@/lib/types';
import { setTauri } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const DISMISS_KEY = 'curio.authgate.dismissed';

function status(
  over: { pixiv?: Partial<SourcesStatus['pixiv']>; twitter?: Partial<SourcesStatus['twitter']> } = {},
) {
  return {
    pixiv: { authed: false, user_id: null, verified: null, checked_at: null, error: null, ...over.pixiv },
    twitter: { authed: false, gallery_dl: true, cookies_file: false, from_browser: null, ...over.twitter },
    network: { resolver: 'system', proxy: false },
  } satisfies SourcesStatus;
}

describe('useSources getters', () => {
  it('pixivOk needs a stored AND verified session', () => {
    const src = useSources();

    expect(src.pixivOk).toBe(false); // no status yet
    src.status = status({ pixiv: { authed: true, verified: true } });
    expect(src.pixivOk).toBe(true);
    src.status = status({ pixiv: { authed: true, verified: null } });
    expect(src.pixivOk).toBe(false);
    src.status = status({ pixiv: { authed: true, verified: false } });
    expect(src.pixivOk).toBe(false);
    src.status = status({ pixiv: { authed: false, verified: true } });
    expect(src.pixivOk).toBe(false);
  });

  it('pixivPending is a stored session whose check has not answered', () => {
    const src = useSources();
    src.status = status({ pixiv: { authed: true, verified: null } });

    expect(src.pixivPending).toBe(true);
    src.status = status({ pixiv: { authed: true, verified: true } });
    expect(src.pixivPending).toBe(false);
    src.status = status({ pixiv: { authed: false, verified: null } });
    expect(src.pixivPending).toBe(false);
  });

  it('anyConnected counts either source', () => {
    const src = useSources();
    src.status = status();

    expect(src.anyConnected).toBe(false);
    src.status = status({ twitter: { authed: true } });
    expect(src.anyConnected).toBe(true);
  });

  it('needsGate only once the status is known, nothing connected, not dismissed', () => {
    const src = useSources();

    expect(src.needsGate).toBe(false); // status unknown: do not flash the gate
    src.status = status();
    expect(src.needsGate).toBe(true);
    src.status = status({ pixiv: { authed: true, verified: true } });
    expect(src.needsGate).toBe(false);
    src.status = status();
    src.dismiss();
    expect(src.needsGate).toBe(false);
  });

  it('dismiss() persists per install', () => {
    useSources().dismiss();

    expect(localStorage.getItem(DISMISS_KEY)).toBe('1');
    setActivePinia(createPinia());
    expect(useSources().dismissed).toBe(true);
    expect(useSources().needsGate).toBe(false);
  });

  it('inTauri reflects the bridge global (decided once per store)', () => {
    expect(useSources().inTauri).toBe(false);
    setTauri(true);
    setActivePinia(createPinia());
    expect(useSources().inTauri).toBe(true);
  });
});

describe('useSources actions', () => {
  it('load() fetches /api/sources/status', async () => {
    const s = status({ pixiv: { authed: true, verified: true } });
    vi.mocked(api.get).mockResolvedValueOnce(s);
    const src = useSources();
    await src.load();

    expect(api.get).toHaveBeenCalledWith('/api/sources/status');
    expect(src.status).toEqual(s);
  });

  it('submit("pixiv") posts the cookie as php_sessid and stores the answer', async () => {
    const s = status({ pixiv: { authed: true, verified: true, user_id: '42' } });
    vi.mocked(api.post).mockResolvedValueOnce(s);
    const src = useSources();
    await src.submit('pixiv', { PHPSESSID: '42_abc' });

    expect(api.post).toHaveBeenCalledWith('/api/auth/pixiv', { php_sessid: '42_abc' });
    expect(src.status).toEqual(s);
    expect(src.busy).toBeNull();
    expect(src.error).toBe('');
  });

  it('submit("twitter") posts auth_token and ct0', async () => {
    vi.mocked(api.post).mockResolvedValueOnce(status({ twitter: { authed: true } }));
    await useSources().submit('twitter', { auth_token: 'a', ct0: 'c' });

    expect(api.post).toHaveBeenCalledWith('/api/auth/twitter', { auth_token: 'a', ct0: 'c' });
  });

  it('submit() records the daemon error, clears busy and rethrows', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(401, 'pixiv_invalid', 'session rejected'));
    const src = useSources();

    await expect(src.submit('pixiv', { PHPSESSID: 'bad' })).rejects.toBeInstanceOf(ApiError);
    expect(src.error).toBe('session rejected');
    expect(src.busy).toBeNull();
  });

  it('disconnect() deletes the session then reloads status', async () => {
    vi.mocked(api.del).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockResolvedValueOnce(status());
    const src = useSources();
    src.status = status({ pixiv: { authed: true, verified: true } });
    await src.disconnect('pixiv');

    expect(api.del).toHaveBeenCalledWith('/api/auth/pixiv');
    expect(api.get).toHaveBeenCalledWith('/api/sources/status');
    expect(src.pixivOk).toBe(false);
  });
});
