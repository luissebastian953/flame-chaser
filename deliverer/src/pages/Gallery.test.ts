import { flushPromises } from '@vue/test-utils';
import Gallery from './Gallery.vue';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn() },
  mediaUrl: (sha: string) => `/media/${sha}`,
}));

async function mountPage(review: unknown) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
  });

  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/api/watches') return [];
    if (path === '/api/gallery/review') return review;
    return {};
  });

  const w = mountWithPlugins(Gallery, { global: { plugins: [router] } });
  await flushPromises();
  return w;
}

describe('Gallery review card', () => {
  it('says what Smart would flag today and links each character with Smart preselected', async () => {
    const w = await mountPage({
      min_score: 0.42,
      total: 17,
      characters: [
        { slug: 'firefly', label: 'Firefly', count: 9 },
        { slug: 'ganyu', label: 'Ganyu', count: 8 },
      ],
    });

    expect(w.text()).toContain('17 below 0.42 across 2 characters');
    const links = w.findAll('a').map((a) => a.attributes('href'));
    expect(links).toContain('/gallery/firefly?delete=smart');
    expect(w.text()).toContain('Firefly · 9');
    expect(w.text()).toContain('Review');
  });

  it('stays quiet when nothing is flagged', async () => {
    const w = await mountPage({ min_score: 0.42, total: 0, characters: [] });

    expect(w.text()).not.toContain('below');
  });
});
