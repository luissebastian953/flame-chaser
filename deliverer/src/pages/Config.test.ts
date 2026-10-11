import { flushPromises } from '@vue/test-utils';
import Config from './Config.vue';
import type { Watch } from '@/lib/types';
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

async function mountPage() {
  vi.mocked(api.get).mockImplementation(async (path: string) => (path === '/api/watches' ? [mei] : []));
  vi.mocked(api.post).mockResolvedValue({ job_id: 'j1' });
  const w = mountWithPlugins(Config, { global: { plugins: [router] } });
  await flushPromises();

  return w;
}

const button = (w: Awaited<ReturnType<typeof mountPage>>, text: string) =>
  w.findAll('button').find((b) => b.text() === text)!;

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

describe('Config new characters', () => {
  it('start from the Settings default gender filter', async () => {
    useCharacterDefaults().set('male', 'partial');
    const w = await mountPage();

    await button(w, 'Add character').trigger('click');
    const pressed = w.findAll('.gender button[aria-pressed="true"]').map((b) => b.text());
    expect(pressed).toEqual(['Male', 'Partial']);
  });
});
