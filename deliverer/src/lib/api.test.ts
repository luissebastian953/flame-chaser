/**
 * lib/api.ts is the only file that knows the daemon's address and token, so
 * these tests pin down exactly how that knowledge leaks out: the bearer
 * header, the ?token= query for <img>/EventSource routes, and the error shape.
 *
 * discover() caches the endpoint in a module-level variable, so every test
 * re-imports a fresh copy of the module.
 */
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(async () => {
    throw new Error('not inside Tauri');
  }),
}));

const BASE = 'http://127.0.0.1:4321';
const TOKEN = 'tok en+1';

async function freshApi() {
  vi.resetModules();
  return import('@/lib/api');
}

function json(status: number, body: unknown, statusText = '') {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.stubEnv('VITE_DAEMON_URL', BASE);
  vi.stubEnv('VITE_DAEMON_TOKEN', TOKEN);
});

describe('discover', () => {
  it('falls back to VITE_DAEMON_URL/TOKEN outside Tauri', async () => {
    const { discover } = await freshApi();

    await expect(discover()).resolves.toEqual({ base: BASE, token: TOKEN });
  });

  it('throws when neither Tauri nor the env vars are available', async () => {
    vi.stubEnv('VITE_DAEMON_URL', '');
    vi.stubEnv('VITE_DAEMON_TOKEN', '');
    const { discover } = await freshApi();

    await expect(discover()).rejects.toThrow(/no daemon endpoint/);
  });

  it('prefers the Tauri handshake when the shell answers', async () => {
    const core = await import('@tauri-apps/api/core');
    vi.mocked(core.invoke).mockResolvedValueOnce({ port: 5555, token: 'shell' });
    const { discover } = await freshApi();

    await expect(discover()).resolves.toEqual({ base: 'http://127.0.0.1:5555', token: 'shell' });
  });

  it('caches the endpoint after the first call', async () => {
    const { discover } = await freshApi();
    const first = await discover();
    vi.stubEnv('VITE_DAEMON_URL', 'http://127.0.0.1:1');

    expect(await discover()).toBe(first);
  });
});

describe('api', () => {
  it('sends the bearer token and parses JSON', async () => {
    const fetchMock = vi.fn(async () => json(200, { ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    const { api } = await freshApi();

    await expect(api.get<{ ok: boolean }>('/api/health')).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];

    expect(url).toBe(`${BASE}/api/health`);
    expect(init.method).toBe('GET');
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
    expect(init.body).toBeUndefined();
  });

  it('serialises a body as JSON with the content type', async () => {
    const fetchMock = vi.fn(async () => json(200, {}));
    vi.stubGlobal('fetch', fetchMock);
    const { api } = await freshApi();

    await api.post('/api/jobs', { type: 'poll_pixiv', params: { slug: 'kiana' } });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];

    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body as string)).toEqual({ type: 'poll_pixiv', params: { slug: 'kiana' } });
  });

  it('resolves undefined for 204 No Content', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 204 })),
    );

    const { api } = await freshApi();

    await expect(api.del('/api/watches/kiana')).resolves.toBeUndefined();
  });

  it('throws ApiError carrying the daemon error code and message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(401, { error: { code: 'pixiv_unauthenticated', message: 'sign in first' } })),
    );

    const { api, ApiError } = await freshApi();
    const err = await api.post('/api/jobs').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, code: 'pixiv_unauthenticated', message: 'sign in first' });
  });

  it('falls back to the status text when the error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<html>', { status: 502, statusText: 'Bad Gateway' })),
    );

    const { api, ApiError } = await freshApi();
    const err = await api.get('/api/health').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 502, code: 'error', message: 'Bad Gateway' });
  });
});

describe('authedUrl / mediaUrl', () => {
  it('refuse to build a URL before discover()', async () => {
    const { authedUrl, mediaUrl } = await freshApi();

    expect(() => authedUrl('/api/preview/1/thumb')).toThrow(/discover\(\) first/);
    expect(() => mediaUrl('abc')).toThrow(/discover\(\) first/);
  });

  it('append the token as an encoded query parameter', async () => {
    const { discover, authedUrl, mediaUrl } = await freshApi();
    await discover();
    const enc = encodeURIComponent(TOKEN);

    expect(authedUrl('/api/preview/1/thumb')).toBe(`${BASE}/api/preview/1/thumb?token=${enc}`);
    expect(mediaUrl('deadbeef')).toBe(`${BASE}/api/media/deadbeef/thumb?token=${enc}`);
    expect(mediaUrl('deadbeef', 'full')).toBe(`${BASE}/api/media/deadbeef/full?token=${enc}`);
  });
});
