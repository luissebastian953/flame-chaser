/**
 * Entry of the mini window (pip.html). Listens for `pipeline:tick` from the
 * main window, renders it, and sends the user's clicks back as `pip:*`
 * events. Drag is native (`data-tauri-drag-region` on the header); when the
 * window stops moving for 120 ms it asks the shell to snap to the nearer
 * screen edge and reports where it landed. The page also asks the shell
 * for the height its rows need, so the window follows the row count.
 */
import { invoke } from '@tauri-apps/api/core';
import { emitTo, listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import '@fontsource/chakra-petch/500.css';
import '@fontsource/chakra-petch/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import './pip.css';
import { PIP_EVENTS, type PipPlacement, type PipTick } from './protocol';
import { render } from './render';

const MAIN = 'main';
const root = document.getElementById('pip')!;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let last: PipTick | null = null;
let lastHeight = 0;
/** the character runs unfolded into their parts; the page's own state */
const open = new Set<string>();

const handlers = {
  focusMain: () => void emitTo(MAIN, PIP_EVENTS.focusMain),
  hide: () => void emitTo(MAIN, PIP_EVENTS.dismiss),
  openLane: (id: string) => void emitTo(MAIN, PIP_EVENTS.openLane, id),
  toggleExpanded: () => void emitTo(MAIN, PIP_EVENTS.expand, !(last?.expanded ?? false)),
  pauseAll: () => void emitTo(MAIN, PIP_EVENTS.pauseAll),
  toggleGroup: (key: string) => {
    if (!open.delete(key)) open.add(key);
    if (last) paint(last);
  },
};

function paint(tick: PipTick) {
  last = tick;
  render(root, tick, handlers, open);
  document.body.classList.toggle('still', reduced || document.visibilityState !== 'visible');
  const height = Math.ceil(root.getBoundingClientRect().height);
  if (height && height !== lastHeight) {
    lastHeight = height;
    invoke('pip_resize', { height }).catch(() => {});
  }
}

document.addEventListener('visibilitychange', () => {
  if (last) paint(last);
});

// snap after the drag settles; ignore the moves our own snap produces
let moveTimer: ReturnType<typeof setTimeout> | undefined;
let snapping = false;

async function snap() {
  if (snapping) return;
  snapping = true;
  try {
    const placed = await invoke<PipPlacement>('pip_snap', { reduced });
    await emitTo(MAIN, PIP_EVENTS.placed, placed);
  } catch {
    /* window already gone */
  } finally {
    setTimeout(() => (snapping = false), 150);
  }
}

async function boot() {
  await listen<PipTick>(PIP_EVENTS.tick, (ev) => paint(ev.payload));

  await getCurrentWindow().onMoved(() => {
    if (snapping) return;
    clearTimeout(moveTimer);
    moveTimer = setTimeout(snap, 120);
  });

  await emitTo(MAIN, PIP_EVENTS.ready);
}

boot().catch(() => {});
