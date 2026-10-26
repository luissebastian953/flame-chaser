import ShutdownConfirm from './ShutdownConfirm.vue';
import { mountWithPlugins } from '@/test/utils';
import type { Job, Watch } from '@/lib/types';

function job(over: Partial<Job> & { id: string; state: Job['state'] }): Job {
  return {
    type: 'poll',
    params: {},
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '2026-10-25T00:00:00+00:00',
    started_at: null,
    finished_at: null,
    lane: 'pixiv',
    worker: null,
    position: 0,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

const ganyu: Watch = {
  slug: 'ganyu',
  label: 'Ganyu',
  pixiv_tags: ['甘雨'],
  sources: ['pixiv', 'twitter'],
  target: 300,
  kind_filter: true,
  gender: 'any',
  gender_mode: 'full',
  match_terms: [],
  min_bookmarks: 0,
  include_r18: false,
};

function mountWith(jobs: Job[]) {
  return mountWithPlugins(ShutdownConfirm, {
    attachTo: document.body,
    pinia: { initialState: { jobs: { jobs }, library: { watches: [ganyu] } } },
  });
}

describe('ShutdownConfirm', () => {
  it('says what is running and queued, with the character, source and progress', () => {
    const w = mountWith([
      job({
        id: 'r',
        state: 'running',
        params: { watches: ['ganyu'], source: 'twitter', target: 300 },
        counters: { posts: 184 },
      }),
      job({ id: 'q1', state: 'queued', position: 1 }),
      job({ id: 'q2', state: 'queued', position: 2 }),
      job({ id: 'q3', state: 'queued', position: 3 }),
      job({ id: 'old', state: 'succeeded' }),
    ]);

    const text = w.text();
    expect(text).toContain('Shut down Curio?');
    expect(text).toContain('1 job running');
    expect(text).toContain('Ganyu · X · 184 / 300 posts');
    expect(text).toContain('stops at its next record');
    expect(text).toContain('3 queued jobs');
    expect(text).not.toContain('No jobs running');
    w.unmount();
  });

  it('collapses to one line when nothing runs, and pixiv progress comes from done / total', () => {
    const idle = mountWith([]);
    expect(idle.text()).toContain('No jobs running');
    idle.unmount();

    const w = mountWith([
      job({
        id: 'p',
        state: 'running',
        params: { watches: ['ganyu'], source: 'pixiv' },
        done: 40,
        total: 120,
      }),
    ]);

    expect(w.text()).toContain('Ganyu · pixiv · 40 / 120 posts');
    w.unmount();
  });

  it('No has focus, Esc and the scrim say no, Yes confirms', async () => {
    const w = mountWith([]);
    const [no, yes] = w.findAll('.foot .btn');
    expect(document.activeElement).toBe(no!.element);
    expect(yes!.text()).toContain('Yes, shut down');

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    expect(w.emitted('close')).toHaveLength(1);
    await w.find('.scrim').trigger('click');
    expect(w.emitted('close')).toHaveLength(2);
    await no!.trigger('click');
    expect(w.emitted('close')).toHaveLength(3);
    expect(w.emitted('confirm')).toBeUndefined();

    await yes!.trigger('click');
    expect(w.emitted('confirm')).toHaveLength(1);
    w.unmount();
  });
});
