<script setup lang="ts">
import { linkedStart, megabytes } from '@/lib/related';

/**
 * Fullscreen viewer over everything, including the rail (stores/viewer.ts).
 * Shows the stored original from the daemon (`/api/media/{sha}/full`, never
 * a file path -- the webview does not touch the filesystem) at fit, 1:1 or
 * 200%, with drag-pan and wheel zoom around the cursor; ← → walk the related
 * set, Space or a double-click toggles fit ↔ 1:1, 0 / 1 / 2 pick a preset,
 * Esc closes. The chrome fades after 2 s without the mouse moving.
 */
const viewer = useViewer();
const src = useSources();
const { t, te } = useI18n();

const cur = computed(() => viewer.current);

function srcLabel(s: string) {
  const key = `gallery.aside.source.${s}`;
  return te(key) ? t(key) : s;
}

// ---- stage geometry: the image is laid out at its native size and transformed ----
const root = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const stageSize = ref({ w: 0, h: 0 });
const natural = ref({ w: 0, h: 0 });
const loaded = ref(false);
const scale = ref(1);
const tx = ref(0);
const ty = ref(0);

/** the scale that shows the whole image; never above 1 (no upscaling at "fit") */
const fitScale = computed(() => {
  const { w, h } = natural.value;
  const s = stageSize.value;
  if (!w || !h || !s.w || !s.h) return 1;
  return Math.min(s.w / w, s.h / h, 1);
});

const PRESETS = { fit: () => fitScale.value, one: () => 1, two: () => 2 } as const;

/** which segment is lit: a preset when the scale matches one, else none (free wheel zoom) */
const active = computed(() => {
  const near = (a: number, b: number) => Math.abs(a - b) < 0.001;
  if (near(scale.value, fitScale.value)) return 'fit';
  if (near(scale.value, 1)) return 'one';
  if (near(scale.value, 2)) return 'two';
  return null;
});

const pannable = computed(
  () =>
    natural.value.w * scale.value > stageSize.value.w || natural.value.h * scale.value > stageSize.value.h,
);

function clampPan() {
  const maxX = Math.max(0, (natural.value.w * scale.value - stageSize.value.w) / 2);
  const maxY = Math.max(0, (natural.value.h * scale.value - stageSize.value.h) / 2);
  tx.value = Math.min(maxX, Math.max(-maxX, tx.value));
  ty.value = Math.min(maxY, Math.max(-maxY, ty.value));
}

function applyPreset() {
  scale.value = PRESETS[viewer.zoom]();
  tx.value = 0;
  ty.value = 0;
}

const imgStyle = computed(() => ({
  width: `${natural.value.w}px`,
  height: `${natural.value.h}px`,
  transform: `translate(calc(-50% + ${tx.value}px), calc(-50% + ${ty.value}px)) scale(${scale.value})`,
}));

// a new image: its row already says the size, so fit is right before a byte arrives
watch(
  () => cur.value?.key,
  () => {
    loaded.value = false;
    natural.value = { w: cur.value?.width ?? 0, h: cur.value?.height ?? 0 };
    applyPreset();
  },
  { immediate: true },
);

watch(() => viewer.zoom, applyPreset);

watch(fitScale, () => {
  if (viewer.zoom === 'fit' && active.value !== 'fit') applyPreset();
});

function onLoad(e: Event) {
  const el = e.target as HTMLImageElement;
  if (el.naturalWidth && el.naturalHeight) natural.value = { w: el.naturalWidth, h: el.naturalHeight };
  loaded.value = true;
  if (viewer.zoom === 'fit') applyPreset();
  else clampPan();
}

// ---- wheel zoom around the cursor, drag to pan ----
function onWheel(e: WheelEvent) {
  e.preventDefault();
  if (!stage.value) return;
  const rect = stage.value.getBoundingClientRect();
  const cx = e.clientX - rect.left - rect.width / 2;
  const cy = e.clientY - rect.top - rect.height / 2;
  const from = scale.value;
  const to = Math.min(8, Math.max(Math.min(fitScale.value, 1) * 0.5, from * Math.exp(-e.deltaY * 0.0015)));
  // keep the pixel under the cursor where it is
  tx.value = cx - (to / from) * (cx - tx.value);
  ty.value = cy - (to / from) * (cy - ty.value);
  scale.value = to;
  clampPan();
}

const drag = ref<{ x: number; y: number } | null>(null);

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0 || !pannable.value) return;
  drag.value = { x: e.clientX, y: e.clientY };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}

function onPointerMove(e: PointerEvent) {
  if (!drag.value) return;
  tx.value += e.clientX - drag.value.x;
  ty.value += e.clientY - drag.value.y;
  drag.value = { x: e.clientX, y: e.clientY };
  clampPan();
}

function onPointerUp() {
  drag.value = null;
}

// ---- chrome fades after 2 s idle; reduced motion keeps it ----
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const idle = ref(false);
let idleTimer: ReturnType<typeof setTimeout> | undefined;

function wake() {
  idle.value = false;
  clearTimeout(idleTimer);
  if (!reduced) idleTimer = setTimeout(() => (idle.value = true), 2000);
}

// ---- keys, in the capture phase so the page's Esc (close the panel) never sees them ----
function onKey(e: KeyboardEvent) {
  const handled = () => {
    e.preventDefault();
    e.stopPropagation();
  };

  switch (e.key) {
    case 'Escape':
      handled();
      viewer.close();
      return;
    case 'ArrowLeft':
      handled();
      viewer.step(-1);
      return;
    case 'ArrowRight':
      handled();
      viewer.step(1);
      return;
    case ' ':
      handled();
      viewer.toggleZoom();
      return;
    case '0':
      handled();
      viewer.setZoom('fit');
      return;
    case '1':
      handled();
      viewer.setZoom('one');
      return;
    case '2':
      handled();
      viewer.setZoom('two');
      return;
  }
}

let ro: ResizeObserver | undefined;

onMounted(() => {
  window.addEventListener('keydown', onKey, true);
  if (stage.value) {
    const measure = () => {
      const r = stage.value!.getBoundingClientRect();
      stageSize.value = { w: r.width, h: r.height };
    };

    measure();
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      ro.observe(stage.value);
    }
  }
  root.value?.focus();
  wake();
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey, true);
  ro?.disconnect();
  clearTimeout(idleTimer);
});

const divider = computed(() => linkedStart(viewer.items));
const canReveal = computed(() => src.inTauri && !!cur.value?.path);

const sub = computed(() => {
  const c = cur.value;
  if (!c) return '';
  const parts = [c.artist_handle || c.artist_name, srcLabel(c.source), (c.posted_at ?? '').slice(0, 10)];
  if (c.pages > 1) parts.push(t('gallery.aside.viewer.pageOf', { n: c.page, total: c.pages }));
  return parts.filter(Boolean).join(' · ');
});
</script>

<template>
  <div
    v-if="cur"
    ref="root"
    class="viewer"
    :class="{ idle, reduced }"
    role="dialog"
    aria-modal="true"
    :aria-label="cur.title || cur.sha.slice(0, 12)"
    tabindex="-1"
    @mousemove="wake"
  >
    <div class="chrome top">
      <button
        class="xbtn"
        :title="$t('gallery.aside.viewer.close')"
        :aria-label="$t('gallery.aside.viewer.close')"
        @click="viewer.close()"
      >
        <Icon name="close" :size="14" />
      </button>
      <div class="who">
        <div class="jp ttl">{{ cur.title || $t('gallery.aside.untitled') }}</div>
        <div class="mono sub">{{ sub }}</div>
        <div v-if="!cur.stored" class="mono rec">{{ $t('gallery.aside.viewer.recorded') }}</div>
      </div>
      <div class="spacer" />
      <span class="mono dims">
        {{
          $t('gallery.aside.viewer.meta', {
            w: natural.w,
            h: natural.h,
            mb: megabytes(cur.bytes),
            ext: cur.ext.toUpperCase(),
          })
        }}
      </span>
      <div class="seg" role="group" :aria-label="$t('gallery.aside.viewer.zoom')">
        <button :class="{ on: active === 'fit' }" @click="viewer.setZoom('fit')">
          {{ $t('gallery.aside.viewer.fit') }}
        </button>
        <button :class="{ on: active === 'one' }" @click="viewer.setZoom('one')">
          {{ $t('gallery.aside.viewer.one') }}
        </button>
        <button :class="{ on: active === 'two' }" @click="viewer.setZoom('two')">
          {{ $t('gallery.aside.viewer.two') }}
        </button>
      </div>
      <button class="btn gh sm" @click="openExternal(cur.permalink)">
        <Icon name="external" :size="12" />
        {{ $t('gallery.aside.openOn', { source: srcLabel(cur.source) }) }}
      </button>
      <button
        class="btn gh sm"
        :disabled="!canReveal"
        :title="
          canReveal
            ? $t('gallery.aside.revealHint')
            : cur.path
              ? $t('gallery.aside.revealDesktop')
              : $t('gallery.aside.revealNone')
        "
        @click="cur.path && revealInFolder(cur.path)"
      >
        <Icon name="folder" :size="12" />
        {{ $t('gallery.aside.reveal') }}
      </button>
    </div>

    <div
      ref="stage"
      class="stage"
      :class="{ grab: pannable, dragging: !!drag }"
      @wheel="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="viewer.toggleZoom()"
    >
      <!-- the gallery thumb, blurred, until the original decodes -->
      <img v-if="!loaded" class="ph" :src="mediaUrl(cur.sha)" :style="imgStyle" alt="" draggable="false" />
      <img
        :key="cur.sha"
        class="full"
        :class="{ ready: loaded }"
        :src="mediaUrl(cur.sha, 'full')"
        :style="imgStyle"
        alt=""
        draggable="false"
        @load="onLoad"
      />
    </div>

    <template v-if="viewer.total > 1">
      <button
        class="arrow chrome left"
        :title="$t('gallery.aside.viewer.prev')"
        :aria-label="$t('gallery.aside.viewer.prev')"
        @click="viewer.step(-1)"
      >
        <Icon name="chevron-left" :size="18" />
      </button>
      <button
        class="arrow chrome right"
        :title="$t('gallery.aside.viewer.next')"
        :aria-label="$t('gallery.aside.viewer.next')"
        @click="viewer.step(1)"
      >
        <Icon name="chevron-right" :size="18" />
      </button>
      <div class="film chrome">
        <template v-for="(it, i) in viewer.items" :key="it.key">
          <i v-if="i === divider" class="div" aria-hidden="true" />
          <button
            class="fth"
            :class="{ cur: i === viewer.index, dim: !it.stored }"
            :title="it.linked ? srcLabel(it.source) : $t('gallery.aside.related.page', { n: it.page })"
            :aria-current="i === viewer.index || undefined"
            @click="viewer.go(i)"
          >
            <img :src="mediaUrl(it.sha)" alt="" draggable="false" />
          </button>
        </template>
        <span class="mono ct">
          {{ $t('gallery.aside.viewer.related', { n: viewer.index + 1, total: viewer.total }) }}
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.viewer {
  position: fixed;
  inset: 0;
  z-index: 50;
  background:
    linear-gradient(color-mix(in oklch, var(--cyan) 3%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in oklch, var(--cyan) 3%, transparent) 1px, transparent 1px),
    oklch(0.09 0.018 265);
  background-size:
    44px 44px,
    44px 44px,
    auto;
  outline: none;
  user-select: none;
}
.chrome {
  transition: opacity 0.25s ease-out;
}
.idle .chrome {
  opacity: 0;
  pointer-events: none;
}
.reduced .chrome {
  transition: none;
}
.top {
  position: absolute;
  inset: 0 0 auto 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(180deg, oklch(0.09 0.018 265 / 0.95), transparent);
}
.xbtn {
  width: 27px;
  height: 27px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  background: oklch(0.15 0.024 265 / 0.7);
  color: var(--tx);
}
.who {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ttl {
  font-size: 13px;
  font-weight: 600;
  color: var(--tx);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub,
.dims {
  font-size: 11px;
  color: var(--mut);
}
.rec {
  font-size: 10px;
  color: var(--dim);
}
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  height: 25px;
}
.seg button {
  padding: 0 9px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--mut);
  background: transparent;
}
.seg button + button {
  border-left: 1px solid var(--line-soft);
}
.seg button.on {
  color: var(--ember);
  background: color-mix(in oklch, var(--ember) 18%, transparent);
}
.stage {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.stage.grab {
  cursor: grab;
}
.stage.dragging {
  cursor: grabbing;
}
.stage img {
  position: absolute;
  left: 50%;
  top: 50%;
  transform-origin: center;
  max-width: none;
  outline: 1px solid var(--line-soft);
  box-shadow: 0 30px 80px oklch(0 0 0 / 0.6);
  will-change: transform;
}
.ph {
  filter: blur(8px);
}
.full {
  opacity: 0;
}
.full.ready {
  opacity: 1;
}
.arrow {
  position: absolute;
  top: 50%;
  z-index: 2;
  width: 36px;
  height: 56px;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  background: oklch(0.15 0.024 265 / 0.7);
  color: var(--tx);
}
.arrow.left {
  left: 18px;
}
.arrow.right {
  right: 18px;
}
.film {
  position: absolute;
  bottom: 16px;
  left: 50%;
  z-index: 2;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--line);
  background: oklch(0.15 0.024 265 / 0.78);
  backdrop-filter: blur(6px);
  max-width: calc(100% - 120px);
  overflow-x: auto;
  scrollbar-width: none;
}
.fth {
  flex: none;
  width: 44px;
  height: 44px;
  padding: 0;
  overflow: hidden;
  opacity: 0.65;
  border: 1px solid var(--line-soft);
  background: var(--bg);
}
.fth img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.fth.cur {
  opacity: 1;
  box-shadow:
    inset 0 0 0 2px var(--ember),
    0 0 10px color-mix(in oklch, var(--ember) 50%, transparent);
}
.fth.dim img {
  opacity: 0.7;
}
.div {
  width: 1px;
  align-self: stretch;
  margin: 6px 2px;
  background: var(--line-soft);
}
.ct {
  flex: none;
  padding: 0 8px 0 6px;
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--dim);
}
</style>
