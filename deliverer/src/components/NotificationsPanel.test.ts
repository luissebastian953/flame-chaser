/**
 * Settings › Notifications: the dropdown drives the persisted mode, the
 * mini window's sub-options follow it, and where a floating window cannot
 * exist the panel says so instead of offering it.
 */
import { flushPromises } from '@vue/test-utils';
import { mountWithPlugins, setTauri } from '@/test/utils';
import NotificationsPanel from './NotificationsPanel.vue';

const KEY = 'curio.background.v1';
const invoke = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));

describe('NotificationsPanel', () => {
  it('shows the current mode and its hint', async () => {
    setTauri(true);
    invoke.mockResolvedValue({ supported: true, reason: null });
    const w = mountWithPlugins(NotificationsPanel);
    await flushPromises();

    expect(w.text()).toContain('While crawling in background');
    expect(w.text()).toContain('Mini window');
    expect(w.text()).toContain('Appears 1.5 s after Curio loses focus');
    expect(w.text()).toContain('Start expanded');
    expect(w.text()).not.toContain('Wayland');
  });

  it('sub-options follow the mode and persist', async () => {
    setTauri(true);
    invoke.mockResolvedValue({ supported: true, reason: null });
    const w = mountWithPlugins(NotificationsPanel);
    await flushPromises();
    const bg = useBackground();

    const boxes = w.findAll('.rk-checkbox');
    expect(boxes).toHaveLength(2);
    expect(boxes[0]!.attributes('disabled')).toBeUndefined();
    await boxes[0]!.trigger('click');
    expect(bg.startExpanded).toBe(true);
    expect(JSON.parse(localStorage.getItem(KEY)!).startExpanded).toBe(true);

    bg.set({ mode: 'notify' });
    await flushPromises();
    expect(w.text()).toContain('One system notification per finished run');
    expect(w.findAll('.rk-checkbox')[0]!.attributes('disabled')).toBeDefined();
  });

  it('on Wayland the saved mini window turns into notifications and the note says why', async () => {
    setTauri(true);
    invoke.mockResolvedValue({ supported: false, reason: 'wayland' });
    const w = mountWithPlugins(NotificationsPanel);
    await flushPromises();

    expect(useBackground().mode).toBe('notify');
    expect(w.text()).toContain('On Linux Wayland');
    expect(w.text()).toContain('falls back to');
  });

  it('in the browser the panel says the desktop app is needed', async () => {
    const w = mountWithPlugins(NotificationsPanel);
    await flushPromises();

    expect(invoke).not.toHaveBeenCalled();
    expect(w.text()).toContain('need the desktop app');
  });
});
