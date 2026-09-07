import { flushPromises } from '@vue/test-utils';
import WatchForm from './WatchForm.vue';
import type { Watch } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

// the form only needs useRouter() to resolve; "connect" pushes /settings in browser mode
const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
});

// the probe would hit the daemon on every tag change; nothing here is about it
vi.mock('@/lib/api', () => ({
  api: { post: vi.fn(async () => ({ tags: [], suggestions: [], preview: [] })) },
}));

function blank(over: Partial<Watch> = {}): Watch {
  return {
    slug: '',
    label: 'Kiana',
    pixiv_tags: ['キアナ'],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv', 'twitter'],
    ...over,
  };
}

function mountForm(watch = blank()) {
  return mountWithPlugins(WatchForm, {
    props: { watch, isNew: true },
    pinia: { stubActions: true },
    global: { plugins: [router] },
  });
}

const box = (w: ReturnType<typeof mountForm>, id: string) => w.find(`#${id}`);

const saveBtn = (w: ReturnType<typeof mountForm>) =>
  w.findAll('button').find((b) => b.text() === 'Save only')!;

describe('WatchForm sources', () => {
  it('starts with both sources ticked and their editors shown', () => {
    const w = mountForm();

    expect(box(w, 'src-pixiv').attributes('data-state')).toBe('checked');
    expect(box(w, 'src-twitter').attributes('data-state')).toBe('checked');
    expect(w.find('.rows').exists()).toBe(true);
    expect(w.find('.chips').exists()).toBe(true);
  });

  it('unticking X hides its editor and saves sources without it', async () => {
    const w = mountForm();

    await box(w, 'src-twitter').trigger('click');
    expect(w.find('.chips').exists()).toBe(false);
    expect(w.findAll('.sec.off')).toHaveLength(1);
    await saveBtn(w).trigger('click');
    await flushPromises();
    const [saved] = w.emitted('save')![0] as [Watch, boolean];

    expect(saved.sources).toEqual(['pixiv']);
  });

  it('refuses to save with no source ticked', async () => {
    const w = mountForm();

    await box(w, 'src-pixiv').trigger('click');
    await box(w, 'src-twitter').trigger('click');
    await saveBtn(w).trigger('click');
    expect(w.emitted('save')).toBeUndefined();
    expect(w.text()).toContain('tick at least one source');
  });

  it('X-only: pixiv tags are not required, but a match term is', async () => {
    const w = mountForm(blank({ pixiv_tags: [] }));

    await box(w, 'src-pixiv').trigger('click');
    await saveBtn(w).trigger('click');
    expect(w.emitted('save')).toBeUndefined();
    expect(w.text()).toContain('X needs at least one match term');

    const w2 = mountForm(blank({ pixiv_tags: [], match_terms: ['kiana'], sources: ['twitter'] }));

    await saveBtn(w2).trigger('click');
    const [saved] = w2.emitted('save')![0] as [Watch, boolean];

    expect(saved.sources).toEqual(['twitter']);
    expect(saved.pixiv_tags).toEqual([]);
  });
});
