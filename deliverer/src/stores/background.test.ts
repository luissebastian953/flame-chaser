/**
 * The background-mode store is per-install state: it must round-trip
 * through localStorage, ignore junk, and fall back to notifications where a
 * floating window cannot exist.
 */
import { setTauri } from '@/test/utils';

const KEY = 'curio.background.v1';
const invoke = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));

describe('useBackground', () => {
  it('starts on the mini window, right side, collapsed', () => {
    const bg = useBackground();

    expect(bg.mode).toBe('mini');
    expect(bg.side).toBe('right');
    expect(bg.expanded).toBe(false);
    expect(bg.trayKeepsProgress).toBe(true);
    expect(bg.supported).toBeNull();
  });

  it('hydrates from localStorage and drops values it does not know', () => {
    localStorage.setItem(KEY, JSON.stringify({ mode: 'none', side: 'up', y: 120 }));
    const bg = useBackground();

    expect(bg.mode).toBe('none');
    expect(bg.side).toBe('right');
    expect(bg.y).toBe(120);

    localStorage.setItem(KEY, JSON.stringify({ mode: 'loud' }));
    setActivePinia(createPinia());
    expect(useBackground().mode).toBe('mini');

    localStorage.setItem(KEY, '{nope');
    setActivePinia(createPinia());
    expect(useBackground().mode).toBe('mini');
  });

  it('persists a patch and resets', () => {
    const bg = useBackground();

    bg.set({ mode: 'notify', expanded: true });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ mode: 'notify', expanded: true });
    bg.reset();
    expect(bg.mode).toBe('mini');
    expect(JSON.parse(localStorage.getItem(KEY)!).expanded).toBe(false);
  });

  it('outside the desktop app nothing floats: notifications apply instead', async () => {
    const bg = useBackground();
    await bg.probe();

    expect(bg.supported).toBe(false);
    expect(bg.reason).toBe('browser');
    expect(bg.mode).toBe('notify');
    expect(bg.coerced).toBe(true);
    expect(invoke).not.toHaveBeenCalled();
  });

  it('on Wayland a saved mini window is coerced to notifications and says so', async () => {
    setTauri(true);
    invoke.mockResolvedValueOnce({ supported: false, reason: 'wayland' });
    const bg = useBackground();
    await bg.probe();

    expect(invoke).toHaveBeenCalledWith('pip_supported');
    expect(bg.reason).toBe('wayland');
    expect(bg.effectiveMode).toBe('notify');
    expect(bg.coerced).toBe(true);
    expect(JSON.parse(localStorage.getItem(KEY)!).mode).toBe('notify');
  });

  it('where it is supported the saved mode stands', async () => {
    setTauri(true);
    invoke.mockResolvedValueOnce({ supported: true, reason: null });
    const bg = useBackground();
    await bg.probe();

    expect(bg.supported).toBe(true);
    expect(bg.effectiveMode).toBe('mini');
    expect(bg.coerced).toBe(false);
  });
});
