import { flushPromises } from '@vue/test-utils';
import Config from './Config.vue';
import type { Job, Watch } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
});

const mei: Watch = {
  slug: 'raiden-mei',
  label: 'Raiden Mei',
  pixiv_tags: [],
  match_terms: ['raiden mei'],
  min_bookmarks: 0,
  include_r18: false,
  sources: ['twitter'],
  target: 300,
  kind_filter: true,
  gender: 'any',
  gender_mode: 'full',
  post_count: 36,
};

/** A finished crawl; `finished_at` doubles as every timestamp. */
function poll(id: string, finished_at: string, counters: Record<string, number>): Job {
  return {
    id,
    type: 'poll',
    params: {},
    state: 'succeeded',
    stage: null,
    done: 0,
    total: null,
    counters,
    error: null,
    created_at: finished_at,
    started_at: finished_at,
    finished_at,
    lane: 'pixiv',
    worker: 'pixiv',
    position: 1,
    paused: false,
    req_per_min: 0,
  };
}

async function mountPage(watches: Watch[] = [mei], jobList: Job[] = []) {
  vi.mocked(api.get).mockImplementation(async (path: string) =>
    path === '/api/watches' ? watches : path.startsWith('/api/jobs') ? jobList : [],
  );

  vi.mocked(api.post).mockResolvedValue({ job_id: 'j1' });
  const w = mountWithPlugins(Config, { global: { plugins: [router] } });
  await flushPromises();

  return w;
}

type Page = Awaited<ReturnType<typeof mountPage>>;

const button = (w: Page, text: string) => w.findAll('button').find((b) => b.text() === text)!;
const card = (w: Page, i: number) => w.findAll('.card')[i]!;
const squash = (s: string) => s.replace(/\s+/g, ' ').trim();

describe('Config runs', () => {
  it("shows each character's posts per run in the table", async () => {
    const w = await mountPage();

    expect(w.text()).toContain('Per run');
    expect(w.find('tbody').text()).toContain('300');
  });

  it('Run and Run all send no number: each character crawls to its own posts per run', async () => {
    const w = await mountPage();

    await button(w, 'Run').trigger('click');
    await flushPromises();
    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'poll', params: { watches: ['raiden-mei'] } });

    await button(w, 'Run all now').trigger('click');
    await flushPromises();
    expect(api.post).toHaveBeenLastCalledWith('/api/jobs', { type: 'poll', params: {} });
  });
});

describe('Config row job state', () => {
  const queued = (id: string): Job => ({
    ...poll(id, '', {}),
    state: 'queued',
    finished_at: null,
    params: { watches: ['raiden-mei'] },
  });

  it('a queued crawl replaces Run with a queued chip into the pipeline', async () => {
    const w = await mountPage([mei], [queued('q1'), queued('q2')]);

    expect(w.find('.actions').text()).toContain('queued ×2');
    expect(w.findAll('.actions button').map((b) => b.text())).toEqual(['Edit']);
  });

  it('a running crawl shows its stage and posts in the worker colour', async () => {
    const running: Job = {
      ...poll('r1', '', { posts: 27 }),
      state: 'running',
      stage: 'discover',
      worker: 'twitter',
      finished_at: null,
      params: { watches: ['raiden-mei'], source: 'twitter' },
    };

    const w = await mountPage([mei], [running]);
    const chip = w.find('.actions .chip.live');

    expect(chip.text()).toContain('discover · 27 new');
    expect(chip.attributes('href')).toBe('/pipeline/twitter');
  });

  it('a crawl that just finished leaves a done chip beside Run', async () => {
    const done: Job = {
      ...poll('d1', new Date().toISOString(), { posts: 12 }),
      params: { watches: ['raiden-mei'] },
    };

    const w = await mountPage([mei], [done]);

    expect(w.find('.actions').text()).toContain('done · +12');
    expect(button(w, 'Run').exists()).toBe(true);
  });

  it('Run on one character stays on Crawl; Run all opens the pipeline', async () => {
    await router.push('/config');
    const w = await mountPage();
    await button(w, 'Run').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/config');

    await button(w, 'Run all now').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/pipeline');
  });

  it("Run raises a toast that follows the character's own crawl jobs, not the shared timelines job", async () => {
    const w = await mountPage();

    const planned = [
      { ...queued('tw'), params: { watches: ['raiden-mei'], source: 'twitter' }, lane: 'twitter' as const },
      { ...queued('tl'), type: 'timelines', params: { accounts: 3 }, lane: 'twitter' as const },
    ];

    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'tw', job_ids: ['tw', 'tl'] });

    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === '/api/watches' ? [mei] : path.startsWith('/api/jobs') ? planned : [],
    );

    await button(w, 'Run').trigger('click');
    await flushPromises();

    const toasts = useToasts().items;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({ kind: 'run', slug: 'raiden-mei', label: 'Raiden Mei', jobIds: ['tw'] });
    // the row chip pulses once
    expect(w.find('.actions .chip.pulse').exists()).toBe(true);
  });

  it('a refused run is an error toast with the daemon code; Run all then stays on Crawl', async () => {
    await router.push('/config');
    const w = await mountPage();
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(400, 'nothing_to_run', 'no character matches'));

    await button(w, 'Run all now').trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.path).toBe('/config');
    expect(useToasts().items[0]).toMatchObject({ kind: 'error', slug: null, code: 'nothing_to_run' });
  });

  it('no answer from the daemon is an "unreachable" error toast', async () => {
    const w = await mountPage();
    vi.mocked(api.post).mockRejectedValueOnce(new TypeError('Failed to fetch'));

    await button(w, 'Run').trigger('click');
    await flushPromises();

    expect(useToasts().items[0]).toMatchObject({ kind: 'error', slug: 'raiden-mei', code: 'unreachable' });
  });
});

describe('Config new characters', () => {
  it('start from the Settings default gender filter', async () => {
    useCharacterDefaults().set('male', 'partial');
    const w = await mountPage();

    await button(w, 'Add character').trigger('click');
    const pressed = w.findAll('.gender button[aria-pressed="true"]').map((b) => b.text());
    expect(pressed).toEqual(['Male', 'Partial']);
  });
});

describe('Config crawl status cards', () => {
  it('Last run reads the newest finished crawl; the footer sums the posts checked over the last runs', async () => {
    const w = await mountPage();
    expect(squash(card(w, 0).text())).toContain('never');
    expect(card(w, 0).text()).toContain('no crawl yet');

    const recent = new Date(Date.now() - 4 * 60_000).toISOString();

    useJobs().jobs = [
      { ...poll('live', recent, { downloaded: 5 }), state: 'running', finished_at: null }, // still going
      poll('j2', recent, { downloaded: 38, listed: 900 }),
      { ...poll('lbl', recent, { downloaded: 99 }), type: 'label' }, // not a crawl
      poll('j1', '2026-10-01T00:00:00Z', { downloaded: 12, listed: 600 }),
    ];

    await nextTick();

    expect(card(w, 0).find('.meta').text()).toBe('4m ago');
    expect(card(w, 0).find('.big b').text()).toBe('+38');
    expect(card(w, 0).find('.big span').text()).toBe('new images');
    expect(squash(card(w, 0).find('.foot').text())).toBe('1,500 posts checked · last 2 runs');
    // eight slots: six empty before the first crawl, then a bar per run, the newest lit and tallest
    const bars = card(w, 0).findAll('.bars i');
    expect(bars).toHaveLength(8);
    expect(bars.map((b) => b.classes('none'))).toEqual([true, true, true, true, true, true, false, false]);

    expect(bars.map((b) => b.classes('now'))).toEqual([
      false,
      false,
      false,
      false,
      false,
      false,
      false,
      true,
    ]);

    expect(bars.slice(-2).map((b) => b.attributes('style'))).toEqual(['height: 9px;', 'height: 30px;']);
  });

  it('Per run shows one number when every character agrees and a range when they differ', async () => {
    const w = await mountPage();
    expect(card(w, 1).find('.big b').text()).toBe('300');
    expect(card(w, 1).find('.big span').text()).toBe('posts / character');
    expect(card(w, 1).find('.meta').text()).toBe('max 1,000');
    expect(w.findAll('.ruler i.on')).toHaveLength(6);

    useLibrary().watches = [mei, { ...mei, slug: 'b', target: 1000 }];
    await nextTick();
    expect(card(w, 1).find('.big b').text()).toBe('300–1,000');
    expect(w.findAll('.ruler i.on')).toHaveLength(20);
  });

  it('Recognition is the kept share of the last crawl, with the counts under it', async () => {
    const w = await mountPage();
    expect(card(w, 2).find('.big b').text()).toBe('—');
    expect(card(w, 2).find('.big span').text()).toBe('of images kept');

    useJobs().jobs = [poll('j', '2026-10-01T00:00:00Z', { downloaded: 38, rejected: 17 })];
    await nextTick();
    expect(card(w, 2).find('.big b').text()).toBe('69%');
    expect(squash(card(w, 2).find('.foot').text())).toBe('38 kept 17 dropped');
  });

  it('Sources shows each sign-in state and the free space on the library disk', async () => {
    const w = await mountPage();

    useSources().status = {
      pixiv: { authed: true, user_id: '1', verified: true, checked_at: 1, error: null },
      twitter: { authed: false, gallery_dl: true, cookies_file: false, from_browser: null },
      network: { resolver: 'system', proxy: false },
    };

    useEndpoint().health = {
      ok: true,
      version: '0.1.0',
      library_root: '/lib',
      db_path: '/db',
      library_free_bytes: 482 * 1024 ** 3,
      schema_version: 1,
      idle: true,
      last_event_id: 0,
    };

    await nextTick();

    const rows = card(w, 3)
      .findAll('.srcs > div')
      .map((r) => squash(r.text()));

    expect(rows).toEqual(['pixiv valid', 'X not linked', 'Library 482 GiB free']);
    expect(card(w, 3).find('a').attributes('href')).toBe('/settings'); // memory history: no hash
  });
});

describe('Config watched characters table', () => {
  const ganyu: Watch = {
    ...mei,
    slug: 'ganyu',
    label: 'Ganyu',
    pixiv_tags: ['甘雨', '甘雨(原神)', '甘雨(飛花逐月)', 'ガンユー', '甘雨(Genshin)'],
    match_terms: ['ganyu', '甘雨'],
  };

  const firefly: Watch = {
    ...mei,
    slug: 'firefly',
    label: 'Firefly',
    pixiv_tags: ['流蛍'],
    match_terms: ['firefly', '流蛍', 'ホタル', 'sam'],
  };

  it('more than two tags or terms fold into "+N more" (total − 2), two or fewer wrap as usual', async () => {
    const w = await mountPage([ganyu, firefly]);
    const [g, f] = w.findAll('tbody tr');

    // Ganyu: five tags fold, two terms do not
    expect(g!.findAll('.chips').map((c) => c.classes('more'))).toEqual([true, false]);
    expect(g!.text()).toContain('+3 more');
    expect(g!.findAll('.chips .chip')).toHaveLength(7); // every chip stays in the DOM, clipped by CSS

    // Firefly: one tag, four terms
    expect(f!.findAll('.chips').map((c) => c.classes('more'))).toEqual([false, true]);
    expect(f!.text()).toContain('+2 more');
  });

  it('"+N more" opens that character for editing', async () => {
    const w = await mountPage([ganyu, firefly]);
    expect(w.findComponent({ name: 'WatchForm' }).exists()).toBe(false);

    await button(w, '+2 more').trigger('click');
    const form = w.findComponent({ name: 'WatchForm' });
    expect(form.exists()).toBe(true);
    expect((form.props('watch') as Watch).slug).toBe('firefly');
  });

  it('every row ends with Edit then Run', async () => {
    const w = await mountPage([ganyu, firefly]);
    for (const row of w.findAll('tbody tr')) {
      expect(row.findAll('.actions button').map((b) => b.text())).toEqual(['Edit', 'Run']);
    }
  });
});
