/**
 * The mini window's renderer: collapsed shows the focused row and an "N+
 * more" toggle, expanded shows every row, the footer carries the totals
 * and Pause all, and each control reports through its handler.
 */
import type { PipHandlers } from './render';
import { render, visibleRows } from './render';
import type { PipRow, PipTick } from './protocol';

const strings = {
  crawling: 'crawling',
  paused: 'paused',
  offline: 'paused · no internet',
  queued: 'queued',
  more: '{n}+ more',
  less: 'Show less',
  pauseAll: 'Pause all',
  resumeAll: 'Resume all',
  newToday: '+{n} new',
  rpm: '{n} req/min',
  open: 'Open Curio',
  hide: 'Hide',
  finished: 'done · +{n} new',
};

const row = (id: string, p: Partial<PipRow> = {}): PipRow => ({
  id,
  name: id.toUpperCase(),
  source: 'pixiv',
  color: 'var(--ember)',
  stage: 'download',
  done: 19,
  total: 27,
  posts: 184,
  target: 300,
  queued: false,
  group: id,
  groupName: id.toUpperCase(),
  ...p,
});

const tick = (p: Partial<PipTick> = {}): PipTick => ({
  paused: false,
  offline: false,
  rows: [row('a'), row('b', { source: 'X', stage: 'discover' }), row('c', { queued: true, stage: 'queued' })],
  focusedId: 'a',
  newToday: 57,
  rpm: 48,
  expanded: false,
  finished: null,
  strings,
  lang: 'en',
  theme: {},
  ...p,
});

function handlers(): PipHandlers {
  return {
    focusMain: vi.fn(),
    hide: vi.fn(),
    openLane: vi.fn(),
    toggleExpanded: vi.fn(),
    pauseAll: vi.fn(),
    toggleGroup: vi.fn(),
  };
}

describe('visibleRows', () => {
  it('collapsed: the focused row alone; expanded: every row', () => {
    expect(visibleRows(tick()).map((r) => r.id)).toEqual(['a']);
    expect(visibleRows(tick({ focusedId: 'b' })).map((r) => r.id)).toEqual(['b']);
    expect(visibleRows(tick({ expanded: true })).map((r) => r.id)).toEqual(['a', 'b', 'c']);
    expect(visibleRows(tick({ rows: [row('z')], focusedId: null })).map((r) => r.id)).toEqual(['z']);
  });
});

describe('render', () => {
  it('collapsed: one row, "2+ more", the totals and Pause all', () => {
    const root = document.createElement('div');
    const h = handlers();
    render(root, tick(), h);

    expect(root.querySelectorAll('.row')).toHaveLength(1);
    expect(root.querySelector('.title')!.textContent).toBe('crawling');
    expect(root.querySelector('.more')!.textContent).toBe('2+ more');
    expect(root.querySelector('.meta')!.textContent).toBe('+57 new · 48 req/min');
    expect(root.querySelector('.pause')!.textContent).toBe('Pause all');
    expect(root.querySelector('.nums')!.textContent).toBe('19 / 27184/300');
  });

  it('expanded: every row, "Show less"; queued rows are marked', () => {
    const root = document.createElement('div');
    render(root, tick({ expanded: true }), handlers());

    expect(root.querySelectorAll('.row')).toHaveLength(3);
    expect(root.querySelectorAll('.row.queued')).toHaveLength(1);
    expect(root.querySelector('.more')!.textContent).toBe('Show less');
  });

  it("expanded: a character's parts fold into one line that unfolds on click", () => {
    const rows = [
      row('x', { name: 'Marin', source: 'X', group: 'marin', groupName: 'Marin', stage: 'discover' }),
      row('tl', {
        name: 'X · followed timelines',
        source: 'X',
        group: 'marin',
        groupName: 'Marin',
        queued: true,
        stage: 'queued',
      }),
      row('k', { name: 'Kafka', group: 'kafka', groupName: 'Kafka', queued: true, stage: 'queued' }),
    ];

    const root = document.createElement('div');
    const h = handlers();
    render(root, tick({ rows, focusedId: 'x', expanded: true }), h);

    const lines = [...root.querySelectorAll('.row')];
    expect(lines).toHaveLength(2); // Marin folded, Kafka alone
    expect(lines[0]!.classList.contains('grp')).toBe(true);
    expect(lines[0]!.querySelector('.nm b')!.textContent).toBe('Marin');
    expect(lines[0]!.querySelector('.stage')!.textContent).toBe('discover'); // the running part leads
    expect(root.textContent).not.toContain('followed timelines');

    (lines[0] as HTMLElement).click();
    expect(h.toggleGroup).toHaveBeenCalledWith('marin');

    render(root, tick({ rows, focusedId: 'x', expanded: true }), h, new Set(['marin']));
    const parts = [...root.querySelectorAll('.row.part')];
    expect(parts.map((p) => p.querySelector('.nm b')!.textContent)).toEqual(['X', 'X · followed timelines']);
    expect(root.querySelector('.row.grp')!.getAttribute('aria-expanded')).toBe('true');
    (parts[1] as HTMLElement).click();
    expect(h.openLane).toHaveBeenCalledWith('tl');
  });

  it('paused and done states change the header and the button', () => {
    const root = document.createElement('div');
    render(root, tick({ paused: true }), handlers());
    expect(root.querySelector('.title')!.textContent).toBe('paused');
    expect(root.querySelector('.pause')!.textContent).toBe('Resume all');

    render(root, tick({ finished: { posts: 38 } }), handlers());
    expect(root.querySelector('.title')!.textContent).toBe('done · +38 new');
    expect(root.querySelector('.panel')!.classList.contains('done')).toBe(true);
  });

  it('a hold for a lost connection says so, as a paused panel', () => {
    const root = document.createElement('div');
    render(root, tick({ paused: true, offline: true }), handlers());
    expect(root.querySelector('.title')!.textContent).toBe('paused · no internet');
    expect(root.querySelector('.panel')!.classList.contains('paused')).toBe(true);
    expect(root.querySelector('.pause')!.textContent).toBe('Resume all');
  });

  it('a single row has no toggle', () => {
    const root = document.createElement('div');
    render(root, tick({ rows: [row('a')] }), handlers());

    expect(root.querySelector('.more')).toBeNull();
  });

  it('controls report through the handlers', () => {
    const root = document.createElement('div');
    const h = handlers();
    render(root, tick(), h);

    (root.querySelector('.row') as HTMLElement).click();
    expect(h.openLane).toHaveBeenCalledWith('a');
    (root.querySelector('.more') as HTMLElement).click();
    expect(h.toggleExpanded).toHaveBeenCalled();
    (root.querySelector('.pause') as HTMLElement).click();
    expect(h.pauseAll).toHaveBeenCalled();
    const [open, hide] = root.querySelectorAll('.ib');
    (open as HTMLElement).click();
    expect(h.focusMain).toHaveBeenCalled();
    (hide as HTMLElement).click();
    expect(h.hide).toHaveBeenCalled();
  });
});
