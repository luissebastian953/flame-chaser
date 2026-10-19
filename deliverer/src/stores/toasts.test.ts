import { TOAST_MAX, TOAST_TTL } from './toasts';

const run = (slug: string) =>
  useToasts().run({ slug, label: slug, sources: ['twitter'], jobIds: [], retry: vi.fn() });

const error = (slug: string) =>
  useToasts().error({
    slug,
    label: slug,
    sources: [],
    terms: 0,
    code: 'nothing_to_run',
    message: 'no character matches',
    retry: vi.fn(),
  });

describe('useToasts', () => {
  beforeEach(() => vi.useFakeTimers());

  afterEach(() => {
    useToasts().clear();
    vi.useRealTimers();
  });

  it('keeps at most three, newest last', () => {
    const toasts = useToasts();
    const ids = ['a', 'b', 'c', 'd'].map((s) => run(s).id);

    expect(toasts.items).toHaveLength(TOAST_MAX);
    expect(toasts.items.map((t) => t.id)).toEqual(ids.slice(1));
  });

  it('a fourth evicts the oldest counting-down toast before any sticky one', () => {
    const toasts = useToasts();
    const sticky = error('held');
    const a = run('a');
    const b = run('b');
    toasts.arm(a.id);
    toasts.arm(b.id);
    const c = run('c');

    expect(toasts.items.map((t) => t.id)).toEqual([sticky.id, b.id, c.id]);
  });

  it('when every toast is sticky the oldest error goes', () => {
    const toasts = useToasts();
    const e1 = error('e1');
    const e2 = error('e2');
    const held = run('held'); // a paused-queue toast: present, never armed
    const next = run('next');

    expect(toasts.items.map((t) => t.id)).toEqual([e2.id, held.id, next.id]);
    expect(toasts.items.find((t) => t.id === e1.id)).toBeUndefined();
  });

  it('arm() dismisses after the ttl; hold() cancels it', () => {
    const toasts = useToasts();
    const a = run('a');
    const b = run('b');
    toasts.arm(a.id);
    toasts.arm(b.id);
    toasts.hold(b.id);

    vi.advanceTimersByTime(TOAST_TTL);
    expect(toasts.items.map((t) => t.id)).toEqual([b.id]);
  });

  it('arm() is a no-op while a countdown runs', () => {
    const toasts = useToasts();
    const a = run('a');
    toasts.arm(a.id);
    vi.advanceTimersByTime(TOAST_TTL - 500);
    toasts.arm(a.id);
    vi.advanceTimersByTime(500);

    expect(toasts.items).toHaveLength(0);
  });

  it('hovering the stack holds every countdown and resumes with the time left', () => {
    const toasts = useToasts();
    const a = run('a');
    toasts.arm(a.id);
    vi.advanceTimersByTime(4000);
    toasts.pauseTimers();
    vi.advanceTimersByTime(60_000);
    expect(toasts.items).toHaveLength(1);
    expect(toasts.held).toBe(true);

    toasts.resumeTimers();
    vi.advanceTimersByTime(1999);
    expect(toasts.items).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(toasts.items).toHaveLength(0);
  });

  it('a toast armed while the stack is hovered starts counting on leave', () => {
    const toasts = useToasts();
    toasts.pauseTimers();
    const a = run('a');
    toasts.arm(a.id);
    vi.advanceTimersByTime(60_000);
    expect(toasts.items).toHaveLength(1);

    toasts.resumeTimers();
    vi.advanceTimersByTime(TOAST_TTL);
    expect(toasts.items).toHaveLength(0);
  });

  it('dismiss() removes the toast and its countdown', () => {
    const toasts = useToasts();
    const a = run('a');
    toasts.arm(a.id);
    toasts.dismiss(a.id);

    expect(toasts.items).toHaveLength(0);
    expect(toasts.armed(a.id)).toBe(false);
  });
});
