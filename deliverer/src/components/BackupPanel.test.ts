/**
 * Settings › Storage › Backup: export submits a job with the webview's own
 * state and follows it through the four stages, then keeps a receipt; a
 * chosen bundle is inspected into a sheet that names new characters and
 * conflicts; the Import button obeys the daemon's gate (pipeline paused and
 * empty); error cards name why a file could not be read; a taken ui state
 * is written back before the reload.
 */
import { flushPromises } from '@vue/test-utils';
import { mountWithPlugins, setTauri } from '@/test/utils';
import { api, ApiError } from '@/lib/api';
import type { BundleInspect, Job } from '@/lib/types';
import BackupPanel from './BackupPanel.vue';

const dialog = { save: vi.fn(), open: vi.fn() };
vi.mock('@tauri-apps/plugin-dialog', () => dialog);
const reveal = vi.fn();
vi.mock('@tauri-apps/plugin-opener', () => ({ revealItemInDir: (...a: unknown[]) => reveal(...a) }));

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

function job(over: Partial<Job>): Job {
  return {
    id: 'j1',
    type: 'export',
    params: {},
    state: 'queued',
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '2026-10-26T00:00:00Z',
    started_at: null,
    finished_at: null,
    lane: 'any',
    worker: null,
    position: 0,
    paused: false,
    req_per_min: 0,
    ...over,
  } as Job;
}

const inspect: BundleInspect = {
  path: '/tmp/archive.curio',
  format: 'curio',
  app_version: '0.1.0',
  schema_version: 12,
  created_at: '2026-10-26T09:00:00+00:00',
  counts: { characters: 3, posts: 40, images: 38, thumbs: 38 },
  has: { images: true, thumbs: true, secrets: false, ui: true },
  characters: [
    { slug: 'firefly', label: 'Firefly', pixiv_tags: ['流螢'], posts: 24, new: false } as never,
    { slug: 'kafka', label: 'Kafka', pixiv_tags: ['カフカ'], posts: 10, new: true } as never,
    { slug: 'sam', label: 'Sam', pixiv_tags: ['流螢', 'サム'], posts: 2, new: true } as never,
  ],
  conflicts: [
    {
      slug: 'firefly',
      label: 'Firefly',
      mine: {} as never,
      theirs: {} as never,
      kind: 'same_slug',
      suggest: null,
    },
    {
      slug: 'sam',
      label: 'Sam',
      mine: {} as never,
      theirs: {} as never,
      kind: 'same_tags',
      suggest: 'firefly',
    },
  ],
};

const idle = { paused: false, workers: [], budgets: [], req_per_min: 0 };

function serveGet(pipeline = idle) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/api/pipeline') return pipeline;
    if (path.startsWith('/api/jobs')) return [];
    if (path === '/api/watches') return [];
    if (path === '/api/health') return {};
    throw new Error(path);
  });
}

const button = (w: ReturnType<typeof mountWithPlugins>, text: string) =>
  w.findAll('button').find((b) => b.text().includes(text));

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  dialog.save.mockReset();
  dialog.open.mockReset();
  reveal.mockReset();
});

describe('BackupPanel · export', () => {
  it('goes through the save dialog, sends the options and the webview state, then follows the stages', async () => {
    setTauri(true);
    localStorage.setItem('curio.theme.v3', JSON.stringify({ preset: 'graphite' }));
    dialog.save.mockResolvedValue('/Users/me/curio-2026.curio');
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1', path: '/Users/me/curio-2026.curio' });

    vi.mocked(api.get).mockResolvedValue([
      job({
        state: 'running',
        stage: 'images',
        done: 21,
        total: 38,
        counters: { posts: 40, images: 38, thumbs: 38, entries: 80 },
      }),
    ]);

    const w = mountWithPlugins(BackupPanel);
    await flushPromises();

    await w.findAll('input[type="radio"]')[1]!.setValue(); // .zip
    await button(w, 'Export…')!.trigger('click');
    await flushPromises();

    expect(dialog.save).toHaveBeenCalledWith(
      expect.objectContaining({ filters: [{ name: 'Zip archive', extensions: ['zip'] }] }),
    );

    expect(api.post).toHaveBeenCalledWith('/api/bundle/export', {
      path: '/Users/me/curio-2026.curio',
      format: 'zip',
      images: true,
      thumbs: true,
      secrets: false,
      ui: { 'curio.theme.v3': { preset: 'graphite' } },
    });

    expect(w.text()).toContain('exporting → /Users/me/curio-2026.curio');
    expect(w.text()).toContain('images 21 / 38');
    const st = w.findAll('.st');

    expect(st.map((s) => s.classes().filter((c) => c !== 'st')[0])).toEqual([
      'done',
      'run',
      'pending',
      'pending',
    ]);

    expect(st[0]!.text()).toContain('40 / 40');
    expect(st[2]!.text()).toContain('0 / 38');
    expect(st[3]!.text()).toContain('0 / 80');
    expect(button(w, 'Export…')!.attributes('disabled')).toBeDefined();
    expect(button(w, 'Choose a bundle')!.attributes('disabled')).toBeDefined();
    expect(w.text()).toContain('not while an export runs');

    // the job lands: receipt with path, size, counts and the reveal button
    useJobs().jobs = [
      job({
        state: 'succeeded',
        stage: 'verify',
        counters: { bytes: 2048, posts: 40, images: 38, thumbs: 38, entries: 80, characters: 2 },
      }),
    ];

    await flushPromises();
    expect(w.text()).toContain('exported · /Users/me/curio-2026.curio');
    expect(w.text()).toContain('38 images · 2 characters');
    expect(w.findAll('.st').every((s) => s.classes().includes('done'))).toBe(true);
    await button(w, 'Show in folder')!.trigger('click');
    await flushPromises();
    expect(reveal).toHaveBeenCalledWith('/Users/me/curio-2026.curio');
  });

  it('a failure keeps the stage counts, turns the stage rose and offers Retry on the same path', async () => {
    setTauri(true);
    dialog.save.mockResolvedValue('/Users/me/x.curio');
    vi.mocked(api.post).mockResolvedValue({ job_id: 'j1', path: '/Users/me/x.curio' });

    vi.mocked(api.get).mockResolvedValue([
      job({
        state: 'failed',
        stage: 'images',
        done: 21,
        total: 38,
        error: 'OSError: ENOSPC',
        counters: { posts: 40, images: 38 },
      }),
    ]);

    const w = mountWithPlugins(BackupPanel);
    await button(w, 'Export…')!.trigger('click');
    await flushPromises();
    expect(w.text()).toContain('export failed · OSError: ENOSPC');
    expect(w.text()).toContain('/Users/me/x.curio.part removed');
    expect(w.findAll('.st')[1]!.classes()).toContain('failed');
    await button(w, 'Retry')!.trigger('click');
    await flushPromises();
    expect(dialog.save).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.post).mock.calls[1]![1]).toMatchObject({ path: '/Users/me/x.curio' });
  });

  it('a dismissed dialog sends nothing; the cookie is a marked risk, off by default', async () => {
    setTauri(true);
    dialog.save.mockResolvedValue(null);
    const w = mountWithPlugins(BackupPanel);
    await button(w, 'Export…')!.trigger('click');
    await flushPromises();
    expect(api.post).not.toHaveBeenCalled();
    expect(w.text()).toContain('anyone holding the file can use the session');
  });

  it('in the browser the daemon picks the path, the thumbnails row follows images, the import takes a typed path', async () => {
    setTauri(false);
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1', path: '/home/me/.reaver/exports/x.curio' });
    vi.mocked(api.get).mockResolvedValue([]);
    const w = mountWithPlugins(BackupPanel);
    expect(w.text()).toContain('browser build');
    expect(w.text()).toContain('written under ~/.reaver/exports');
    await w.findAll('.rk-checkbox')[0]!.trigger('click'); // images off
    expect(w.findAll('.opt.dis')).toHaveLength(1);
    await button(w, 'Export')!.trigger('click');
    await flushPromises();
    const body = vi.mocked(api.post).mock.calls[0]![1] as Record<string, unknown>;
    expect(body).not.toHaveProperty('path');
    expect(body).toMatchObject({ images: false, thumbs: false });
    expect(w.find('input.inp').exists()).toBe(true);
    expect(dialog.save).not.toHaveBeenCalled();
  });
});

describe('BackupPanel · import', () => {
  it('inspects a chosen bundle into the sheet: chips, the policy select, the gate, then the import', async () => {
    setTauri(true);
    dialog.open.mockResolvedValue('/tmp/archive.curio');

    vi.mocked(api.post).mockImplementation(async (path: string) => {
      if (path === '/api/bundle/inspect') return inspect;
      if (path === '/api/pipeline/pause') return { paused: true };
      if (path === '/api/bundle/import') {
        return {
          mode: 'merge',
          damaged: [],
          ui: null,
          characters: 2,
          posts: 10,
          placed: 8,
          dupes: 1,
          refetch: 0,
        };
      }
      throw new Error(path);
    });

    serveGet();
    const w = mountWithPlugins(BackupPanel, { attachTo: document.body });
    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/bundle/inspect', { path: '/tmp/archive.curio' });
    const sheet = w.find('[role="dialog"]');
    expect(sheet.exists()).toBe(true);
    expect(sheet.text()).toContain('archive.curio');
    expect(sheet.text()).toContain('3 characters · 40 posts · 38 images');
    expect(sheet.text()).toContain('Characters · 3');
    expect(sheet.findAll('.tag.new')).toHaveLength(1);
    expect(sheet.find('.tag.bad').text()).toContain('same tags as your firefly');
    const policy = sheet.find('select.policy');
    expect((policy.element as HTMLSelectElement).value).toBe('merge');
    await policy.setValue('keep');
    expect(document.activeElement?.textContent?.trim()).toBe('Cancel');

    // gated until the pipeline is paused and empty
    const run = button(w, 'Import')!;
    expect(run.attributes('disabled')).toBeDefined();
    expect(sheet.text()).toContain('must be paused and empty');
    serveGet({ ...idle, paused: true });
    await button(w, 'Pause the pipeline')!.trigger('click');
    await flushPromises();
    expect(sheet.text()).toContain('pipeline paused and empty');
    expect(run.attributes('disabled')).toBeUndefined();

    await run.trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/bundle/import', {
      path: '/tmp/archive.curio',
      mode: 'merge',
      settings: 'keep',
      secrets: false,
      characters: { firefly: 'keep', sam: 'merge' },
      salvage: true,
    });

    expect(w.find('[role="dialog"]').exists()).toBe(false);
    expect(w.text()).toContain('done:');
    expect(w.text()).toContain('2 characters · 10 posts · 8 images placed · 1 duplicates · 0 to re-download');
    expect(w.text()).toContain('archive.curio · merge');
    w.unmount();
  });

  it('names the daemon error on a card, with the newer-Curio one pointing at Updates', async () => {
    setTauri(true);
    dialog.open.mockResolvedValue('/tmp/notes.zip');
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(400, 'not_a_bundle', 'nope'));
    const w = mountWithPlugins(BackupPanel);
    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();
    expect(w.find('.err.rose').text()).toContain('Not a Curio bundle');
    expect(w.find('.err.rose').text()).toContain('notes.zip · no manifest inside');
    expect(w.find('[role="dialog"]').exists()).toBe(false);

    vi.mocked(api.post).mockRejectedValueOnce(
      new ApiError(400, 'bundle_too_new', 'bundle schema v14; this app knows up to v12'),
    );

    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();
    expect(w.find('.err.neutral').text()).toContain('Made by a newer Curio');
    await button(w, 'Update first')!.trigger('click');
    expect(w.emitted('updates')).toHaveLength(1);

    vi.mocked(api.post).mockRejectedValueOnce(
      new ApiError(400, 'damaged', "the bundle's database does not verify"),
    );

    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();
    expect(w.find('.err.fill').text()).toContain('Damaged where it matters');

    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(400, 'no_file', '/tmp/notes.zip'));
    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();
    expect(w.find('.err.dim').text()).toContain('No such file');
    expect(button(w, 'Choose again')).toBeDefined();
  });

  it('restore forces the bundle settings, shows "replaced", and a taken ui state is written back before the reload', async () => {
    setTauri(true);
    vi.useFakeTimers();
    dialog.open.mockResolvedValue('/tmp/archive.curio');

    vi.mocked(api.post).mockImplementation(async (path: string) => {
      if (path === '/api/bundle/inspect')
        return { ...inspect, has: { ...inspect.has, images: false, secrets: true } };
      return {
        mode: 'restore',
        damaged: ['blobs/abc.png'],
        ui: { 'curio.locale': 'ja' },
        characters: 3,
        posts: 40,
        placed: 37,
        dupes: 0,
        refetch: 1,
      };
    });

    serveGet({ ...idle, paused: true });
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    const w = mountWithPlugins(BackupPanel);
    await button(w, 'Choose a bundle')!.trigger('click');
    await flushPromises();
    const sheet = w.find('[role="dialog"]');
    expect(sheet.text()).toContain('This bundle has no images');
    await sheet.find('input[type="radio"][value="restore"]').setValue();
    await flushPromises();
    expect(sheet.text()).toContain("the bundle's are taken on restore");
    expect(sheet.find('.grp.inert').exists()).toBe(true);

    expect(sheet.findAll('.tag').map((c) => c.text())).toEqual([
      'replaced',
      'new',
      'same tags as your firefly',
    ]);

    expect(sheet.find('select.policy').exists()).toBe(false);

    await button(w, 'Import')!.trigger('click');
    await flushPromises();

    expect(vi.mocked(api.post).mock.calls.at(-1)![1]).toMatchObject({
      mode: 'restore',
      settings: 'take',
      secrets: true,
      characters: {},
    });

    expect(localStorage.getItem('curio.locale')).toBe('ja');
    expect(w.text()).toContain('1 damaged entry skipped');
    await button(w, 'Which')!.trigger('click');
    expect(w.text()).toContain('blobs/abc.png');
    expect(w.text()).toContain('settings applied - reloading');
    vi.runAllTimers();
    expect(reload).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
