/**
 * Settings › Storage: the four plates read GET /api/storage and GET
 * /api/trash; the disk bar is proportional; the trash plate offers Empty
 * only when there is something in it; Reveal is desktop-only.
 */
import { flushPromises } from '@vue/test-utils';
import { mountWithPlugins, setTauri } from '@/test/utils';
import { api } from '@/lib/api';
import type { StorageUsage } from '@/lib/types';
import StoragePanel from './StoragePanel.vue';

const reveal = vi.fn();
vi.mock('@tauri-apps/plugin-opener', () => ({ revealItemInDir: (...a: unknown[]) => reveal(...a) }));

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const usage: StorageUsage = {
  library_root: '/Users/me/Pictures/Curio',
  db_path: '/Users/me/.reaver/reaver.db',
  db_bytes: 48_200_000,
  schema_version: 12,
  disk: {
    total: 494_000_000_000,
    free: 313_000_000_000,
    used: 181_000_000_000,
    library: 41_000_000_000,
    other: 140_000_000_000,
    mount: '/',
  },
  blobs: { files: 1193, bytes: 41_000_000_000 },
  thumbs: { files: 1193, bytes: 186_000_000 },
  by_character: { characters: 2 },
};

function serve(trash: { count: number; bytes: number; oldest: string | null; days: number }) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/api/storage') return usage;
    if (path === '/api/trash') return trash;
    throw new Error(path);
  });
}

describe('StoragePanel', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    reveal.mockReset();
  });

  it('renders the four plates from the daemon figures', async () => {
    setTauri(true);
    serve({ count: 3, bytes: 12_400_000, oldest: null, days: 30 });
    const w = mountWithPlugins(StoragePanel);
    await flushPromises();

    const text = w.text();
    expect(text).toContain('/Users/me/Pictures/Curio');
    expect(text).toContain('/Users/me/.reaver/reaver.db');
    expect(text).toContain('schema v12');
    expect(text).toContain('library 38.2 GiB');
    expect(text).toContain('free 291.5 GiB of 460.1 GiB · /');
    expect(text).toContain('1,193 files · 38.2 GiB');
    expect(text).toContain('2 characters · 0 B extra');
    expect(text).toContain('3 items · 11.8 MiB');
    expect(text).toContain('kept 30 days, then removed');
    expect(text).toContain('The database never lives inside the library folder');
    // the bar is proportional to the disk
    const bars = w.findAll('.bar i');
    expect(bars[0]!.attributes('style')).toContain('8.29');
    expect(bars[1]!.attributes('style')).toContain('28.3');

    await w
      .findAll('button')
      .find((b) => b.text().includes('Show in folder'))!
      .trigger('click');

    await flushPromises();
    expect(reveal).toHaveBeenCalledWith('/Users/me/Pictures/Curio');
  });

  it('an empty trash says so and offers no button; emptying reloads', async () => {
    setTauri(false);
    serve({ count: 0, bytes: 0, oldest: null, days: 30 });
    const w = mountWithPlugins(StoragePanel);
    await flushPromises();
    expect(w.text()).toContain('empty');
    expect(w.findAll('button').some((b) => b.text().includes('Empty trash'))).toBe(false);
    expect(w.findAll('button').some((b) => b.text().includes('Show in folder'))).toBe(false);

    serve({ count: 2, bytes: 1000, oldest: null, days: 30 });
    vi.mocked(api.post).mockResolvedValue({ images: 2, bytes: 1000 });
    const w2 = mountWithPlugins(StoragePanel);
    await flushPromises();
    serve({ count: 0, bytes: 0, oldest: null, days: 30 });

    await w2
      .findAll('button')
      .find((b) => b.text().includes('Empty trash'))!
      .trigger('click');

    await flushPromises();
    expect(api.post).toHaveBeenCalledWith('/api/trash/purge', { everything: true });
    expect(w2.text()).toContain('2 images removed');
  });
});
