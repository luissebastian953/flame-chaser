/**
 * Purge all data: step 1 opens on "galleries only" with Cancel focused and
 * the daemon's counts; Confirm swaps to step 2 in place; Yes stays off until
 * the phrase is typed exactly (trimmed, case-sensitive); Esc and No close
 * from step 2 but not while the purge runs; a failure shows the daemon's
 * words and offers Retry; the full scope clears `curio.*` and reloads.
 */
import { flushPromises } from '@vue/test-utils';
import { mountWithPlugins } from '@/test/utils';
import { api } from '@/lib/api';
import type { PurgePreview, PurgeStatus } from '@/lib/types';
import PurgeSheet from './PurgeSheet.vue';

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const preview: PurgePreview = { images: 1193, characters: 2, posts: 900, bytes: 41_200_000_000 };

function status(over: Partial<PurgeStatus>): PurgeStatus {
  return {
    id: 'p1',
    scope: 'galleries',
    state: 'running',
    done: 0,
    total: 1193,
    error: null,
    result: null,
    ...over,
  };
}

function serve(...steps: PurgeStatus[]) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/api/storage/purge/preview') return preview;
    if (path === '/api/storage/purge/p1') return steps.length > 1 ? steps.shift() : steps[0];
    throw new Error(path);
  });
}

const button = (w: ReturnType<typeof mountWithPlugins>, label: string) =>
  w.findAll('button').find((b) => b.text() === label)!;

const esc = () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

async function toStep2(w: ReturnType<typeof mountWithPlugins>) {
  await button(w, 'Confirm').trigger('click');
  await flushPromises();
}

describe('PurgeSheet', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it('opens on galleries only with Cancel focused, then shows the counts', async () => {
    serve(status({}));
    const w = mountWithPlugins(PurgeSheet, { attachTo: document.body });
    expect(w.text()).toContain('…');
    await flushPromises();

    expect(w.text()).toContain('choose what is removed · this cannot be undone');
    const radios = w.findAll<HTMLInputElement>('input[type="radio"]');
    expect(radios[0]!.element.checked).toBe(true);
    expect(radios[1]!.element.checked).toBe(false);
    expect(document.activeElement?.textContent?.trim()).toBe('Cancel');
    expect(w.text()).toContain('1,193 images · 38.4 GiB');
    expect(w.text()).toContain('1,193 images · 2 characters · 38.4 GiB');

    await button(w, 'Cancel').trigger('click');
    expect(w.emitted('close')).toHaveLength(1);
    w.unmount();
  });

  it('step 2 replaces step 1 and Yes needs the exact phrase', async () => {
    serve(status({}));
    const w = mountWithPlugins(PurgeSheet, { attachTo: document.body });
    await flushPromises();
    await toStep2(w);

    expect(w.text()).toContain('Are you sure?');
    expect(w.text()).toContain('purge galleries only · 1,193 images · 38.4 GiB');
    expect(w.text()).toContain('This cannot be undone');
    expect(document.activeElement?.tagName).toBe('INPUT');
    const yes = () => button(w, 'Yes');
    const input = w.find('input[type="text"]');
    expect(input.attributes('autocomplete')).toBe('off');
    expect(input.attributes('spellcheck')).toBe('false');
    expect(yes().attributes('disabled')).toBeDefined();

    await input.setValue('please delete');
    expect(yes().attributes('disabled')).toBeDefined();
    await input.trigger('keydown', { key: 'Enter' });
    expect(api.post).not.toHaveBeenCalled();

    await input.setValue('  PLEASE DELETE ');
    expect(yes().attributes('disabled')).toBeUndefined();

    esc();
    expect(w.emitted('close')).toHaveLength(1);
    w.unmount();
  });

  it('runs, ignores Esc while running, and hands the outcome back', async () => {
    const result = { scope: 'galleries' as const, images: 1193, bytes: 41_200_000_000, failed: [] };
    serve(status({ done: 412 }), status({ state: 'succeeded', done: 1193, result }));
    vi.mocked(api.post).mockResolvedValue({ job_id: 'p1' });
    vi.useFakeTimers();
    const w = mountWithPlugins(PurgeSheet);
    await flushPromises();
    await w.findAll('input[type="radio"]')[0]!.setValue(true);
    await toStep2(w);
    await w.find('input[type="text"]').setValue('PLEASE DELETE');
    await w.find('input[type="text"]').trigger('keydown', { key: 'Enter' });
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/storage/purge', {
      scope: 'galleries',
      confirm: 'PLEASE DELETE',
    });

    expect(w.text()).toContain('purging… 412 / 1,193 images');
    expect(button(w, 'No').attributes('disabled')).toBeDefined();
    expect(w.find('.x').exists()).toBe(false);
    esc();
    expect(w.emitted('close')).toBeUndefined();

    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(w.emitted('done')).toEqual([[result]]);
    vi.useRealTimers();
  });

  it('a failure shows the daemon error and offers Retry', async () => {
    serve(status({ state: 'failed', error: 'disk on fire' }));
    vi.mocked(api.post).mockResolvedValue({ job_id: 'p1' });
    const w = mountWithPlugins(PurgeSheet);
    await flushPromises();
    await toStep2(w);
    await w.find('input[type="text"]').setValue('PLEASE DELETE');
    await button(w, 'Yes').trigger('click');
    await flushPromises();

    expect(w.text()).toContain('purge failed · disk on fire');
    expect(button(w, 'Retry').attributes('disabled')).toBeUndefined();
    expect(button(w, 'No').attributes('disabled')).toBeUndefined();

    serve(status({ state: 'failed', error: 'still on fire' }));
    await button(w, 'Retry').trigger('click');
    await flushPromises();
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(w.text()).toContain('purge failed · still on fire');

    await button(w, 'No').trigger('click');
    expect(w.emitted('close')).toHaveLength(1);
  });

  it('configs and galleries clears the webview state and reloads', async () => {
    const result = { scope: 'all' as const, images: 1193, bytes: 1, failed: [] };
    serve(status({ scope: 'all', state: 'succeeded', result }));
    vi.mocked(api.post).mockResolvedValue({ job_id: 'p1' });
    const reload = vi.fn();
    const loc = window.location;
    Object.defineProperty(window, 'location', { configurable: true, value: { ...loc, reload } });
    localStorage.setItem('curio.theme.v3', '{}');
    localStorage.setItem('curio.authgate.dismissed', '1');
    localStorage.setItem('other.key', 'kept');

    const w = mountWithPlugins(PurgeSheet);
    await flushPromises();
    await w.findAll('input[type="radio"]')[1]!.setValue(true);
    await toStep2(w);
    expect(w.text()).toContain('purge configs and galleries · 1,193 images · 2 characters');
    await w.find('input[type="text"]').setValue('PLEASE DELETE');
    await button(w, 'Yes').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/storage/purge', { scope: 'all', confirm: 'PLEASE DELETE' });
    expect(localStorage.getItem('curio.theme.v3')).toBeNull();
    expect(localStorage.getItem('curio.authgate.dismissed')).toBeNull();
    expect(localStorage.getItem('other.key')).toBe('kept');
    expect(reload).toHaveBeenCalled();
    expect(w.emitted('done')).toBeUndefined();
    Object.defineProperty(window, 'location', { configurable: true, value: loc });
  });
});
