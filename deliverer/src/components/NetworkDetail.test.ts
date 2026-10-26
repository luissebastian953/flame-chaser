import NetworkDetail from './NetworkDetail.vue';
import { mountWithPlugins } from '@/test/utils';
import { speed } from '@/test/network';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

function mountWith(over = {}, stub = true) {
  const w = mountWithPlugins(NetworkDetail, {
    attachTo: document.body,
    pinia: { stubActions: stub, initialState: { network: { open: true, speed: speed(over) } } },
  });

  return w;
}

describe('NetworkDetail', () => {
  it('shows the three figures, the server and the connection', () => {
    const w = mountWith();
    const text = w.text();
    expect(text).toContain('73.1');
    expect(text).toContain('64.5');
    expect(text).toContain('30.3');
    expect(text).toContain('Singapore');
    expect(text).toContain('IPv4');
    expect(text).toContain('Curio-5G');
    expect(text).toContain('IOH B2B');
    expect(text).toContain('AS4761');
    expect(w.findAll('path.line')).toHaveLength(2);
    w.unmount();
  });

  it('focuses Close on open; Esc and Close dismiss', async () => {
    const w = mountWith();
    const close = w.find('button.pri');
    expect(document.activeElement).toBe(close.element);
    await close.trigger('click');
    expect(useNetwork().hide).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(useNetwork().hide).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it('has no Retest while probes run by themselves; a failed probe brings it back', async () => {
    const w = mountWith();
    expect(w.find('button.gh').exists()).toBe(false);
    useNetwork().speed = speed({ error: 'HTTPStatusError: 503' });
    await nextTick();
    expect(w.find('button.gh').text()).toContain('Retest');
    await w.find('button.gh').trigger('click');
    expect(useNetwork().measure).toHaveBeenCalledWith(true);
    useNetwork().testing = true;
    await nextTick();
    expect(w.find('button.gh').exists()).toBe(false); // gone again while it runs
    expect(w.text()).toContain('73.1'); // the figures stay up
    expect(w.findAll('path.line')).toHaveLength(2); // the chart stays
    w.unmount();
  });

  it('a line that is down shows rose dots and no chart', () => {
    const w = mountWith({
      online: false,
      download_mbps: null,
      samples: { download: [], upload: [] },
      error: 'ConnectError: no route',
    });

    expect(w.findAll('.dot.rose').length).toBeGreaterThanOrEqual(2);
    expect(w.findAll('path.line')).toHaveLength(0);
    expect(w.text()).toContain('ConnectError: no route');
    w.unmount();
  });
});
