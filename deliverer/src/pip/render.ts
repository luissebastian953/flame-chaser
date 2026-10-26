/**
 * The mini window's view, as a pure function of the last tick: build the
 * panel's DOM into a root element. No framework -- this page must stay a
 * few kilobytes (it is a second WebView process). Handlers are passed in
 * so the renderer knows nothing about Tauri and can be tested in a DOM.
 */
import { PIP_MAX_ROWS, type PipRow, type PipTick } from './protocol';

export interface PipHandlers {
  focusMain(): void;
  hide(): void;
  openLane(id: string): void;
  toggleExpanded(): void;
  pauseAll(): void;
  /** unfold / fold a character's run into its parts */
  toggleGroup(key: string): void;
}

/** a character's run: its rows (pixiv half, X half, the sweep behind them) */
export interface PipGroup {
  key: string;
  name: string;
  rows: PipRow[];
}

/** rows folded into character runs, in first-seen order */
export function groupRows(rows: readonly PipRow[]): PipGroup[] {
  const out: PipGroup[] = [];
  const by = new Map<string, PipGroup>();
  for (const r of rows) {
    let g = by.get(r.group);
    if (!g) {
      g = { key: r.group, name: r.groupName, rows: [] };
      by.set(r.group, g);
      out.push(g);
    }
    g.rows.push(r);
  }
  return out;
}

const fill = (s: string, n: number) => s.replace('{n}', String(n));

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(cls: string, label: string, onClick: () => void, text?: string): HTMLButtonElement {
  const b = el('button', cls, text);
  b.type = 'button';
  b.setAttribute('aria-label', label);
  b.title = label;

  b.addEventListener('click', (e) => {
    e.stopPropagation();
    onClick();
  });

  return b;
}

/** the row's progress as a share of its honest denominator, or null */
function pct(r: PipRow): number | null {
  if (r.target) return Math.min(100, Math.round((100 * r.posts) / r.target));
  if (r.total) return Math.min(100, Math.round((100 * r.done) / r.total));
  return null;
}

/** which rows show: the focused one alone, or every row up to the cap (then scroll) */
export function visibleRows(tick: PipTick): PipRow[] {
  if (tick.expanded || tick.rows.length <= 1) return tick.rows;
  const focused = tick.rows.find((r) => r.id === tick.focusedId) ?? tick.rows[0];
  return focused ? [focused] : [];
}

/** the right-hand numbers of a row: stage word, then the honest counts */
function right(r: PipRow): HTMLElement {
  const node = el('div', 'right');
  node.append(el('span', 'stage', r.stage));
  const nums = el('span', 'nums');
  if (r.total !== null) nums.append(el('span', 'dim', `${r.done} / ${r.total}`));
  if (r.target !== null) {
    nums.append(el('b', '', String(r.posts)));
    nums.append(el('span', 'dim', `/${r.target}`));
  } else if (r.total === null) {
    nums.append(el('b', '', String(r.posts)));
  }
  node.append(nums);
  return node;
}

function progress(r: PipRow): HTMLElement {
  const bar = el('div', 'bar' + (pct(r) === null ? ' indet' : ''));
  const fillEl = el('i');
  fillEl.style.width = `${pct(r) ?? 30}%`;
  bar.append(fillEl);
  return bar;
}

/** a character's run folded into one line: a chevron, the name, and the
 *  running part's progress; a click unfolds it into `part` rows */
function groupRow(g: PipGroup, open: boolean, focusedId: string | null, h: PipHandlers): HTMLElement {
  const primary = g.rows.find((r) => r.id === focusedId) ?? g.rows.find((r) => !r.queued) ?? g.rows[0]!;
  const node = el('div', 'row grp' + (open ? ' open' : '') + (primary.queued ? ' queued' : ''));
  node.style.setProperty('--wc', primary.color);
  node.setAttribute('role', 'button');
  node.setAttribute('aria-expanded', String(open));
  node.tabIndex = 0;
  node.addEventListener('click', () => h.toggleGroup(g.key));

  node.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') h.toggleGroup(g.key);
  });

  node.append(el('span', 'ring'));
  const who = el('div', 'who');
  const name = el('div', 'nm');
  name.append(el('span', 'chev', '›'));
  name.append(el('b', '', g.name));
  if (primary.source) name.append(el('span', 'src', primary.source));
  who.append(name);
  who.append(progress(primary));
  node.append(who);
  node.append(right(primary));
  return node;
}

/** `part`: one of a run's rows under its group line -- named by its source
 *  (the pixiv half, the X half) or by itself (the timelines sweep) */
function row(r: PipRow, focused: boolean, h: PipHandlers, part = false): HTMLElement {
  const node = el(
    'div',
    'row' + (part ? ' part' : '') + (r.queued ? ' queued' : '') + (focused ? ' focused' : ''),
  );

  node.style.setProperty('--wc', r.color);
  node.setAttribute('role', 'button');
  node.tabIndex = 0;
  node.addEventListener('click', () => h.openLane(r.id));

  node.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') h.openLane(r.id);
  });

  node.append(el('span', 'ring'));

  const who = el('div', 'who');
  const name = el('div', 'nm');
  const own = part && r.name === r.groupName;
  name.append(el('b', '', own ? r.source || r.name : r.name));
  if (r.source && !own) name.append(el('span', 'src', r.source));
  who.append(name);
  who.append(progress(r));
  node.append(who);
  node.append(right(r));
  return node;
}

/**
 * `open`: the groups the user unfolded. Collapsed, the panel shows the focused
 * row alone; expanded, one line per character run (a run of one row is the row
 * itself), each unfolding into its parts.
 */
export function render(
  root: HTMLElement,
  tick: PipTick,
  h: PipHandlers,
  open: ReadonlySet<string> = new Set(),
): void {
  root.replaceChildren();
  root.lang = tick.lang;
  const s = tick.strings;
  const state = tick.finished ? 'done' : tick.paused ? 'paused' : 'crawling';

  const panel = el('div', `panel ${state}`);

  // header: the drag region; buttons stop propagation so they stay clickable
  const head = el('div', 'head');
  head.setAttribute('data-tauri-drag-region', '');
  head.append(el('i', 'dot'));

  head.append(
    el(
      'span',
      'title',
      tick.finished
        ? fill(s.finished, tick.finished.posts)
        : tick.offline
          ? s.offline
          : tick.paused
            ? s.paused
            : s.crawling,
    ),
  );

  head.append(el('span', 'spacer'));
  head.append(button('ib', s.open, h.focusMain, '↗'));
  head.append(button('ib', s.hide, h.hide, '×'));
  panel.append(head);

  const rows = visibleRows(tick);
  const list = el('div', 'rows');
  let shown = 0;
  if (tick.expanded) {
    for (const g of groupRows(rows)) {
      if (g.rows.length === 1) {
        list.append(row(g.rows[0]!, g.rows[0]!.id === tick.focusedId, h));
        shown += 1;
        continue;
      }
      const unfolded = open.has(g.key);
      list.append(groupRow(g, unfolded, tick.focusedId, h));
      shown += 1;
      if (unfolded) {
        for (const r of g.rows) list.append(row(r, r.id === tick.focusedId, h, true));
        shown += g.rows.length;
      }
    }
  } else {
    for (const r of rows) list.append(row(r, r.id === tick.focusedId, h));
    shown = rows.length;
  }
  if (tick.expanded && shown > PIP_MAX_ROWS) list.classList.add('scroll');
  panel.append(list);

  const hidden = tick.rows.length - rows.length;
  if (tick.rows.length > 1) {
    const label = tick.expanded ? s.less : fill(s.more, hidden);
    panel.append(button('more', label, h.toggleExpanded, label));
  }

  const foot = el('div', 'foot');
  const meta = el('span', 'meta', `${fill(s.newToday, tick.newToday)} · ${fill(s.rpm, tick.rpm)}`);
  foot.append(meta);
  foot.append(el('span', 'spacer'));

  foot.append(
    button(
      'pause',
      tick.paused ? s.resumeAll : s.pauseAll,
      h.pauseAll,
      tick.paused ? s.resumeAll : s.pauseAll,
    ),
  );

  panel.append(foot);

  // the 2 px bar under the panel mirrors the focused job
  const focused = tick.rows.find((r) => r.id === tick.focusedId) ?? tick.rows[0];
  const mirror = el('div', 'mirror' + (focused && pct(focused) === null ? ' indet' : ''));
  const mf = el('i');
  mf.style.width = `${focused ? (pct(focused) ?? 30) : 0}%`;
  if (focused) mirror.style.setProperty('--wc', focused.color);
  mirror.append(mf);
  panel.append(mirror);

  root.append(panel);
}
