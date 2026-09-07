import UpdateBanner from './UpdateBanner.vue';
import { mountWithPlugins } from '@/test/utils';

const MB = 1048576;

function mountAt(updater: Record<string, unknown>) {
  const w = mountWithPlugins(UpdateBanner, { pinia: { stubActions: true, initialState: { updater } } });
  return { w, up: useUpdater() };
}

describe('UpdateBanner', () => {
  it('renders nothing while there is nothing to do', () => {
    for (const phase of ['idle', 'checking', 'error', 'unsupported']) {
      const { w } = mountAt({ phase });

      expect(w.find('.ub').exists(), phase).toBe(false);
    }
  });

  it('announces an available update with version and size, Update starts the download', async () => {
    const { w, up } = mountAt({ phase: 'available', version: '0.2.0', total: 12 * MB });

    expect(w.text()).toContain('New update');
    expect(w.text()).toContain('0.2.0');
    expect(w.text()).toContain('12 MB');
    await w.get('button').trigger('click');
    expect(up.download).toHaveBeenCalledTimes(1);
    expect(up.install).not.toHaveBeenCalled();
  });

  it('omits the size before the download has been sized', () => {
    const { w } = mountAt({ phase: 'available', version: '0.2.0', total: 0 });

    expect(w.text()).not.toContain('MB');
  });

  it('shows the progress percentage while downloading', () => {
    const { w } = mountAt({ phase: 'downloading', version: '0.2.0', total: 4 * MB, done: 3 * MB });

    expect(w.text()).toContain('Updating to 0.2.0');
    expect(w.text()).toContain('75%');
    expect(w.find('button').exists()).toBe(false);
    expect((w.get('.bar > div').element as HTMLElement).style.width).toBe('75%');
  });

  it('offers Restart only when the update is ready', async () => {
    const { w, up } = mountAt({ phase: 'ready', version: '0.2.0' });

    expect(w.text()).toContain('0.2.0 ready');
    expect(w.text()).toContain('restart to finish');
    const btn = w.get('button');

    expect(btn.text()).toBe('Restart');
    await btn.trigger('click');
    expect(up.install).toHaveBeenCalledTimes(1);
  });

  it('explains the idle gate while waiting, with no button', () => {
    const { w } = mountAt({ phase: 'waiting', version: '0.2.0' });

    expect(w.text()).toContain('installs when the current crawl finishes');
    expect(w.find('button').exists()).toBe(false);
  });

  it('shows the restarting state while installing', () => {
    const { w } = mountAt({ phase: 'installing', version: '0.2.0' });

    expect(w.text()).toContain('Restarting');
    expect(w.find('button').exists()).toBe(false);
  });
});
