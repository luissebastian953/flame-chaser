/**
 * The updater is a small state machine over two Tauri plugins. Both are
 * mocked; the tests drive the phases and the one rule that matters most:
 * never install over a running crawl.
 */
import type { Health } from '@/lib/types';
import { setTauri } from '@/test/utils';

vi.mock('@tauri-apps/plugin-updater', () => ({ check: vi.fn() }));
vi.mock('@tauri-apps/plugin-process', () => ({ relaunch: vi.fn() }));

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

import { check, type DownloadEvent } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';

function fakeUpdate() {
  return {
    version: '0.2.0',
    body: '## 0.2.0\n- things',
    date: '2026-09-01',
    download: vi.fn(async (_cb?: (ev: DownloadEvent) => void): Promise<void> => {}),
    install: vi.fn(async (): Promise<void> => {}),
  };
}

function health(idle: boolean): Health {
  return {
    ok: true,
    version: __APP_VERSION__,
    library_root: '/lib',
    db_path: '/db',
    library_free_bytes: 1,
    schema_version: 1,
    idle,
    last_event_id: 0,
  };
}

/** A store whose state was created with the Tauri bridge present. */
function desktopStore() {
  setTauri(true);
  setActivePinia(createPinia());
  return useUpdater();
}

describe('useUpdater', () => {
  it('is unsupported outside Tauri and check() is a no-op there', async () => {
    const up = useUpdater();

    expect(up.phase).toBe('unsupported');
    await up.check();
    expect(check).not.toHaveBeenCalled();
    expect(up.phase).toBe('unsupported');
  });

  it('exposes the build-time version and sha', () => {
    const up = desktopStore();

    expect(up.current).toBe(__APP_VERSION__);
    expect(up.build).toBe(__GIT_SHA__);
  });

  describe('check()', () => {
    it('lands on available with the update metadata', async () => {
      const u = fakeUpdate();
      vi.mocked(check).mockResolvedValueOnce(u as never);
      const up = desktopStore();
      await up.check();

      expect(up.phase).toBe('available');
      expect(up.version).toBe('0.2.0');
      expect(up.notes).toContain('things');
      expect(up.date).toBe('2026-09-01');
      expect(up.lastChecked).not.toBeNull();
      expect(JSON.parse(localStorage.getItem('curio.updater.v1')!).lastChecked).toBe(up.lastChecked);
    });

    it('returns to idle when there is nothing new', async () => {
      vi.mocked(check).mockResolvedValueOnce(null);
      const up = desktopStore();
      up.version = '0.9.9';
      await up.check();

      expect(up.phase).toBe('idle');
      expect(up.version).toBeNull();
      expect(up.update).toBeNull();
    });

    it('records the failure without throwing', async () => {
      vi.mocked(check).mockRejectedValueOnce(new Error('bad pubkey'));
      const up = desktopStore();
      await up.check();

      expect(up.phase).toBe('error');
      expect(up.error).toBe('bad pubkey');
    });

    it('downloads straight away when auto-install is on', async () => {
      const u = fakeUpdate();
      vi.mocked(check).mockResolvedValueOnce(u as never);
      const up = desktopStore();
      up.auto = true;
      await up.check();

      expect(u.download).toHaveBeenCalledTimes(1);
    });
  });

  describe('download()', () => {
    it('tracks Started/Progress/Finished into progress % and ends ready', async () => {
      const u = fakeUpdate();
      let emit!: (ev: DownloadEvent) => void;
      let finish!: () => void;

      u.download.mockImplementation((cb) => {
        emit = cb!;
        return new Promise<void>((r) => (finish = r));
      });

      const up = desktopStore();
      up.update = u as never;
      up.phase = 'available';
      const pending = up.download();

      expect(up.phase).toBe('downloading');
      emit({ event: 'Started', data: { contentLength: 4 * 1048576 } });
      expect(up.total).toBe(4 * 1048576);
      expect(up.mb).toBe('4');
      expect(up.progress).toBe(0);
      emit({ event: 'Progress', data: { chunkLength: 1048576 } });
      expect(up.progress).toBe(25);
      emit({ event: 'Progress', data: { chunkLength: 1048576 } });
      expect(up.progress).toBe(50);
      emit({ event: 'Finished' });
      expect(up.progress).toBe(100);
      finish();
      await pending;

      expect(up.phase).toBe('ready');
    });

    it('does nothing without an update in hand', async () => {
      const up = desktopStore();
      await up.download();

      expect(up.phase).toBe('idle');
    });

    it('fails soft', async () => {
      const u = fakeUpdate();
      u.download.mockRejectedValueOnce(new Error('offline'));
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'available';
      await up.download();

      expect(up.phase).toBe('error');
      expect(up.error).toBe('offline');
    });
  });

  describe('install()', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('installs and relaunches when the daemon is idle', async () => {
      vi.mocked(api.get).mockResolvedValue(health(true));
      const u = fakeUpdate();
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'ready';
      await up.install();

      expect(u.install).toHaveBeenCalledTimes(1);
      expect(relaunch).toHaveBeenCalledTimes(1);
      expect(up.phase).toBe('installing');
    });

    it('waits for the job queue, polling every 5 s, then installs', async () => {
      vi.mocked(api.get).mockResolvedValue(health(false));
      const u = fakeUpdate();
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'ready';
      await up.install();

      expect(up.phase).toBe('waiting');
      expect(u.install).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(5000);
      expect(up.phase).toBe('waiting'); // still busy

      vi.mocked(api.get).mockResolvedValue(health(true));
      await vi.advanceTimersByTimeAsync(5000);

      expect(u.install).toHaveBeenCalledTimes(1);
      expect(relaunch).toHaveBeenCalledTimes(1);
      expect(up.phase).toBe('installing');

      // the poll stopped: no further health calls
      const calls = vi.mocked(api.get).mock.calls.length;
      await vi.advanceTimersByTimeAsync(15000);
      expect(vi.mocked(api.get).mock.calls.length).toBe(calls);
    });

    it('refuses to install from any phase but ready/waiting', async () => {
      const u = fakeUpdate();
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'available';
      await up.install();

      expect(u.install).not.toHaveBeenCalled();
      expect(up.phase).toBe('available');
    });

    it('records an install failure', async () => {
      vi.mocked(api.get).mockResolvedValue(health(true));
      const u = fakeUpdate();
      u.install.mockRejectedValueOnce(new Error('signature'));
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'ready';
      await up.install();

      expect(up.phase).toBe('error');
      expect(up.error).toBe('signature');
      expect(relaunch).not.toHaveBeenCalled();
    });
  });

  describe('setAuto()', () => {
    it('persists and kicks off a pending download', () => {
      const u = fakeUpdate();
      const up = desktopStore();
      up.update = u as never;
      up.phase = 'available';
      up.setAuto(true);

      expect(JSON.parse(localStorage.getItem('curio.updater.v1')!).auto).toBe(true);
      expect(u.download).toHaveBeenCalledTimes(1);
    });

    it('is remembered across store instances', () => {
      desktopStore().setAuto(true);

      expect(desktopStore().auto).toBe(true);
    });
  });

  it('daemonMismatch flags a shell/daemon version drift', () => {
    const up = desktopStore();
    const ep = useEndpoint();

    expect(up.daemonMismatch).toBe(false); // unknown health
    ep.health = { ...health(true), version: '0.0.1-other' };
    expect(up.daemonMismatch).toBe(true);
    ep.health = health(true);
    expect(up.daemonMismatch).toBe(false);
  });
});
