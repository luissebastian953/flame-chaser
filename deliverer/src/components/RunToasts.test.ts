import { flushPromises } from '@vue/test-utils';
import RunToasts from './RunToasts.vue';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
});

const raise = (slug: string) =>
  useToasts().run({ slug, label: slug, sources: ['twitter'], jobIds: [], retry: vi.fn(async () => {}) });

describe('RunToasts', () => {
  afterEach(() => useToasts().clear());

  it('renders one toast per item, newest last', async () => {
    const w = mountWithPlugins(RunToasts, { global: { plugins: [router] } });
    raise('Firefly');
    raise('Kiana');
    await flushPromises();

    const titles = w.findAll('.ttl').map((t) => t.text().replace(/\s+/g, ' '));
    expect(titles).toEqual(['Firefly queued on X', 'Kiana queued on X']);
  });

  it('Esc dismisses the newest toast', async () => {
    mountWithPlugins(RunToasts, { global: { plugins: [router] } });
    raise('Firefly');
    raise('Kiana');
    await flushPromises();

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(useToasts().items.map((t) => t.label)).toEqual(['Firefly']);
  });

  it('hovering the stack holds the countdowns, leaving resumes them', async () => {
    const w = mountWithPlugins(RunToasts, { global: { plugins: [router] } });
    raise('Firefly');
    await flushPromises();

    await w.find('.toasts').trigger('mouseenter');
    expect(useToasts().held).toBe(true);
    await w.find('.toasts').trigger('mouseleave');
    expect(useToasts().held).toBe(false);
  });
});
