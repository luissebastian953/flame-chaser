import { OPEN_REFRESH_MS, POLL_MS, REFRESH_MS, barsFor } from './network';
import { speed } from '@/test/network';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

describe('network bars', () => {
  it('maps download Mbps to bars and a quality word', () => {
    expect([null, 0, 4.9, 5, 24.9, 25, 99.9, 100, 500].map(barsFor)).toEqual([0, 1, 1, 2, 2, 3, 3, 4, 4]);
    const net = useNetwork();
    expect(net.quality).toBe('offline');
    net.speed = speed({ download_mbps: 73.1 });
    expect([net.bars, net.quality]).toEqual([3, 'good']);
    net.speed = speed({ online: false, download_mbps: null });
    expect([net.bars, net.quality, net.online]).toEqual([0, 'offline', false]);
  });
});

describe('network phase', () => {
  it('reads checking, disconnected, no internet, degraded or ok from the last answer', () => {
    const net = useNetwork();
    expect(net.phase).toBe('checking');
    net.speed = speed();
    expect(net.phase).toBe('ok');
    net.speed = speed({ download_mbps: 4.2 });
    expect(net.phase).toBe('degraded');
    net.speed = speed({ latency_ms: 480 });
    expect(net.phase).toBe('degraded');
    net.speed = speed({ online: false, download_mbps: null });
    expect(net.phase).toBe('noInternet');

    net.speed = speed({
      online: false,
      download_mbps: null,
      connection: { interface: null, ssid: null, isp: null, asn: null },
    });

    expect(net.phase).toBe('disconnected');
  });
});

describe('useNetwork actions', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('measures through the daemon and every 30 s after start()', async () => {
    vi.mocked(api.post).mockResolvedValue(speed());
    const net = useNetwork();
    net.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.post).toHaveBeenCalledWith('/api/net/speed', { full: false });
    expect(net.download).toBe(73.1);
    await vi.advanceTimersByTimeAsync(REFRESH_MS);
    expect(api.post).toHaveBeenCalledTimes(2);
    net.start(); // idempotent
    await vi.advanceTimersByTimeAsync(REFRESH_MS);
    expect(api.post).toHaveBeenCalledTimes(3);
    net.stop();
    await vi.advanceTimersByTimeAsync(REFRESH_MS * 2);
    expect(api.post).toHaveBeenCalledTimes(3);
  });

  it('a daemon that does not answer reads as offline until the next answer', async () => {
    const net = useNetwork();
    net.speed = speed();
    vi.mocked(api.post).mockRejectedValueOnce(new Error('ECONNREFUSED'));
    await net.measure();
    expect([net.online, net.bars]).toEqual([false, 0]);
    vi.mocked(api.post).mockResolvedValueOnce(speed());
    await net.measure();
    expect(net.online).toBe(true);
  });

  it('remembers when the line went down and counts down to the next probe', async () => {
    vi.setSystemTime(new Date('2026-10-26T11:14:02Z'));
    vi.mocked(api.post).mockResolvedValue(speed({ online: false, download_mbps: null }));
    const net = useNetwork();
    net.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(net.lostAt).toBe(Date.parse('2026-10-26T11:14:02Z'));
    expect(net.retryIn).toBe(REFRESH_MS / 1000);
    await vi.advanceTimersByTimeAsync(12_000);
    expect(net.lostAgo).toBe(12);
    expect(net.retryIn).toBe(REFRESH_MS / 1000 - 12);
    // a second offline answer keeps the first loss time; a good one clears it
    await vi.advanceTimersByTimeAsync(REFRESH_MS);
    expect(net.lostAgo).toBe(42);
    vi.mocked(api.post).mockResolvedValue(speed());
    await vi.advanceTimersByTimeAsync(REFRESH_MS);
    expect(net.lostAt).toBeNull();
    net.stop();
  });

  it('show() runs the long probe and polls the tape once a second until hide()', async () => {
    vi.mocked(api.post).mockResolvedValue(speed());
    vi.mocked(api.get).mockResolvedValue(speed({ samples: { download: [1, 2], upload: [] } }));
    const net = useNetwork();
    net.show();
    expect(net.open).toBe(true);
    expect(api.post).toHaveBeenCalledWith('/api/net/speed', { full: true });
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(api.get).toHaveBeenCalledTimes(3);
    expect(api.get).toHaveBeenCalledWith('/api/net/speed');
    // every fifth second a short probe instead of a poll, so the tape grows while watched
    await vi.advanceTimersByTimeAsync(OPEN_REFRESH_MS - POLL_MS * 3);
    expect(api.post).toHaveBeenLastCalledWith('/api/net/speed', { full: false });
    expect(api.get).toHaveBeenCalledTimes(4);
    net.hide();
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(api.get).toHaveBeenCalledTimes(4);
    expect(net.open).toBe(false);
  });
});
