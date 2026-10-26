<script setup lang="ts">
import type { DeletePreview } from '@/lib/types';

/**
 * The confirm sheet, shared by every mode: slides in from the right over a
 * scrim on the content (not the rail). A thumbnail strip (click = review
 * lightbox), three stat boxes, the two options (trash · forget posts),
 * warnings, and the primary. All adds a rose strip and the character's name
 * typed back; permanent deletion is a two-second hold.
 */
const props = defineProps<{
  preview: DeletePreview;
  label: string;
  /** the character's posts per run (the forget note) */
  target: number;
  /** badge text per image, for the by-reason box */
  reasons: Record<string, number>;
}>();

const emit = defineEmits<{
  close: [];
  confirm: [opts: { trash: boolean; forget: boolean; confirm?: string }];
}>();

const del = useDeletion();
const fm = useFormats();
const { t } = useI18n();

const all = computed(() => del.mode === 'all');
const forced = computed(() => props.preview.forced_trash);
const trash = ref(true);
const forget = ref(!all.value);
const typed = ref('');
const nameOk = computed(() => !all.value || typed.value.trim() === props.label.trim());
const permanent = computed(() => !trash.value && !forced.value);
const shas = computed(() => del.effective);
const STRIP = 5;

const sub = computed(() => {
  const size = fm.bytes(props.preview.bytes);
  if (all.value) {
    const posts = t(
      'gallery.gallery.postCount',
      { n: fm.number(props.preview.posts.touched) },
      props.preview.posts.touched,
    );

    return t('gallery.delete.sheet.subAll', { label: props.label, size, posts });
  }
  return t('gallery.delete.sheet.sub', {
    label: props.label,
    mode: t(`gallery.delete.sheet.modeName.${del.mode ?? 'image'}`),
    size,
  });
});

const byReason = computed(() =>
  Object.entries(props.reasons)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]),
);

/** hold-to-confirm for a permanent delete: 2 s on the primary */
const holding = ref(false);
const held = ref(0);
let holdTimer: ReturnType<typeof setInterval> | null = null;
const HOLD_MS = 2000;

function holdStart() {
  if (!permanent.value) return;
  holding.value = true;
  held.value = 0;
  const t0 = Date.now();

  holdTimer = setInterval(() => {
    held.value = Math.min(1, (Date.now() - t0) / HOLD_MS);
    if (held.value >= 1) {
      holdEnd();
      go();
    }
  }, 50);
}

function holdEnd() {
  holding.value = false;
  held.value = 0;
  if (holdTimer) clearInterval(holdTimer);
  holdTimer = null;
}

function primary() {
  if (permanent.value) return; // the hold does it
  go();
}

function go() {
  if (!nameOk.value || del.busy) return;

  emit('confirm', {
    trash: trash.value || forced.value,
    forget: forget.value,
    confirm: all.value ? typed.value : undefined,
  });
}

// review lightbox
const lightbox = ref<number | null>(null);

function step(d: number) {
  if (lightbox.value === null) return;
  lightbox.value = (lightbox.value + d + shas.value.length) % shas.value.length;
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    if (lightbox.value !== null) lightbox.value = null;
    else emit('close');
  } else if (lightbox.value !== null && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
    e.preventDefault();
    step(e.key === 'ArrowRight' ? 1 : -1);
  } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !permanent.value) {
    e.preventDefault();
    go();
  }
}

onMounted(() => window.addEventListener('keydown', onKey, true));

onUnmounted(() => {
  window.removeEventListener('keydown', onKey, true);
  holdEnd();
});

const reasonKey = (k: string) =>
  ['score', 'other', 'dupe', 'unidentified', 'kind', 'hand'].includes(k) ? k : 'tag';
</script>

<template>
  <div class="scrim" @click="emit('close')" />
  <aside
    class="sheet"
    role="dialog"
    :aria-label="$t('gallery.delete.sheet.title', { n: preview.images }, preview.images)"
  >
    <div class="head">
      <i class="tick" />
      <div class="ttl">
        {{
          all
            ? $t('gallery.delete.sheet.titleAll', { n: fm.number(preview.images) })
            : $t('gallery.delete.sheet.title', { n: fm.number(preview.images) }, preview.images)
        }}
      </div>
      <div class="spacer" />
      <button class="x" :aria-label="$t('gallery.delete.sheet.close')" @click="emit('close')">
        <Icon name="close" :size="14" />
      </button>
    </div>
    <div class="sub mono">{{ sub }}</div>
    <div class="body">
      <div class="strip">
        <button
          v-for="(sha, i) in shas.slice(0, STRIP)"
          :key="sha"
          class="th"
          :aria-label="$t('gallery.delete.sheet.review', { n: shas.length })"
          @click="lightbox = i"
        >
          <img :src="mediaUrl(sha)" alt="" loading="lazy" />
        </button>
        <button v-if="shas.length > STRIP" class="th more mono" @click="lightbox = STRIP">
          {{ $t('gallery.delete.sheet.more', { n: fm.number(shas.length - STRIP) }) }}
        </button>
      </div>
      <div class="stats">
        <div class="box">
          <span class="ptitle">{{ $t('gallery.delete.sheet.bySource') }}</span>
          <span class="mono">
            {{ $t('gallery.aside.source.pixiv') }} {{ fm.number(preview.by_source.pixiv ?? 0) }} ·
            {{ $t('gallery.aside.source.twitter') }} {{ fm.number(preview.by_source.twitter ?? 0) }}
          </span>
        </div>
        <div class="box">
          <span class="ptitle">{{ $t('gallery.delete.sheet.byReason') }}</span>
          <span class="mono">
            <template v-for="([k, n], i) in byReason" :key="k">
              <template v-if="i">&nbsp;·&nbsp;</template>
              {{ $t(`gallery.delete.sheet.reason.${reasonKey(k)}`, { n: fm.number(n), label: k }) }}
            </template>
          </span>
        </div>
        <div class="box">
          <span class="ptitle">{{ $t('gallery.delete.sheet.posts') }}</span>
          <span class="mono">
            {{ fm.number(preview.posts.touched) }}
            <template v-if="preview.posts.keep_other">
              · {{ $t('gallery.delete.sheet.keepOther', { n: fm.number(preview.posts.keep_other) }) }}
            </template>
          </span>
        </div>
      </div>
      <div v-if="all" class="strip-all">{{ $t('gallery.delete.sheet.allStrip', { label }) }}</div>
      <label class="opt">
        <CheckboxRoot
          :model-value="trash || forced"
          :disabled="forced"
          class="rk-checkbox"
          @update:model-value="(v) => (trash = v === true)"
        />
        <span class="otxt">
          <b>{{ $t('gallery.delete.sheet.trash') }}</b>
          <span class="note">
            {{
              $t('gallery.delete.sheet.trashNote', {
                days: preview.trash.days,
                size: fm.bytes(preview.trash.bytes),
              })
            }}
            <template v-if="forced">· {{ $t('gallery.delete.sheet.trashForced') }}</template>
          </span>
        </span>
      </label>
      <label class="opt">
        <CheckboxRoot
          :model-value="forget"
          :disabled="!preview.posts.forget"
          class="rk-checkbox"
          @update:model-value="(v) => (forget = v === true)"
        />
        <span class="otxt">
          <b>
            {{
              $t('gallery.delete.sheet.forget', { n: fm.number(preview.posts.forget) }, preview.posts.forget)
            }}
          </b>
          <span class="note">
            {{
              all
                ? $t('gallery.delete.sheet.forgetNoteAll')
                : $t('gallery.delete.sheet.forgetNote', { target: fm.number(target) })
            }}
          </span>
        </span>
      </label>
      <div v-if="all" class="field">
        <label>{{ $t('gallery.delete.sheet.typeName', { label }) }}</label>
        <input
          v-model="typed"
          class="jp"
          type="text"
          :placeholder="label"
          autocomplete="off"
          spellcheck="false"
        />
      </div>
      <div v-if="preview.shared || forced || (preview.whole && !all)" class="warns">
        <div v-if="preview.shared" class="warn amber">
          <Icon name="warning" :size="12" />
          {{ $t('gallery.delete.sheet.warnShared', { n: fm.number(preview.shared) }) }}
        </div>
        <div v-if="forced" class="warn amber">
          <Icon name="warning" :size="12" />
          {{ $t('gallery.delete.sheet.warnMany') }}
        </div>
        <div v-if="preview.whole && !all" class="warn rose">
          <Icon name="warning" :size="12" />
          {{ $t('gallery.delete.sheet.warnWhole', { label }) }}
        </div>
      </div>
    </div>
    <div class="foot">
      <span class="mono keys">{{ $t('gallery.delete.sheet.keys') }}</span>
      <button class="btn gh sm" @click="emit('close')">{{ $t('gallery.delete.sheet.cancel') }}</button>
      <button
        class="btn pri go"
        :class="{ holding }"
        :disabled="!nameOk || del.busy || !shas.length"
        :style="permanent ? { '--held': held } : undefined"
        @click="primary"
        @pointerdown="holdStart"
        @pointerup="holdEnd"
        @pointerleave="holdEnd"
      >
        <Icon v-if="del.busy" name="loader" class="spin" :size="12" />
        <Icon v-else name="trash" :size="13" />
        {{
          permanent
            ? $t('gallery.delete.sheet.confirmPermanent', { n: fm.number(shas.length) })
            : $t('gallery.delete.sheet.confirm', { n: fm.number(shas.length) })
        }}
        <span v-if="permanent" class="holdhint mono">{{ $t('gallery.delete.sheet.hold') }}</span>
      </button>
    </div>
  </aside>
  <Teleport to="body">
    <div v-if="lightbox !== null" class="lightbox" @click.self="lightbox = null">
      <button class="nav prev" :aria-label="$t('gallery.delete.sheet.lightbox.prev')" @click="step(-1)">
        <Icon name="chevron-left" :size="18" />
      </button>
      <img :src="mediaUrl(shas[lightbox]!, 'full')" alt="" />
      <button class="nav next" :aria-label="$t('gallery.delete.sheet.lightbox.next')" @click="step(1)">
        <Icon name="chevron-right" :size="18" />
      </button>
      <div class="counter mono">
        {{ $t('gallery.delete.sheet.lightbox.counter', { i: lightbox + 1, n: shas.length }) }}
      </div>
      <button class="lx" :aria-label="$t('gallery.delete.sheet.lightbox.close')" @click="lightbox = null">
        <Icon name="close" :size="16" />
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: absolute;
  inset: 0;
  z-index: 6;
  background: oklch(0 0 0 / 0.45);
}
.sheet {
  position: absolute;
  z-index: 7;
  top: 0;
  right: 0;
  bottom: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  background: color-mix(in oklch, var(--color-surf) 86%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  backdrop-filter: blur(14px) saturate(1.2);
  border-left: 1px solid var(--color-rose);
  box-shadow: -20px 0 50px oklch(0 0 0 / 0.45);
  animation: in 0.22s ease-out;
}
@keyframes in {
  from {
    transform: translateX(40px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 4px;
}
.tick {
  width: 3px;
  height: 14px;
  background: var(--color-rose);
  box-shadow: 0 0 8px var(--color-rose);
}
.ttl {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
  text-transform: uppercase;
}
.sub {
  padding: 0 16px 12px 29px;
  border-bottom: 1px solid var(--color-line-soft);
}
.mono {
  font: 11px var(--font-mono);
  color: var(--color-dim);
}
.x {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  color: var(--color-dim);
  padding: 0;
}
.x:hover {
  color: var(--color-tx);
}
.body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.strip {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 5px;
}
.th {
  aspect-ratio: 1;
  padding: 0;
  border: 1px solid var(--color-line-soft);
  background: var(--color-surf2);
  overflow: hidden;
  cursor: zoom-in;
}
.th img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.th.more {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-tx);
  font-size: 12px;
  cursor: pointer;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.box {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 9px;
  border: 1px solid var(--color-line-soft);
  background: color-mix(in oklch, var(--color-surf2) 60%, transparent);
  min-width: 0;
}
.box .mono {
  color: var(--color-tx);
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.strip-all {
  padding: 9px 11px;
  border: 1px solid color-mix(in oklch, var(--color-rose) 50%, transparent);
  background: color-mix(in oklch, var(--color-rose) 12%, transparent);
  color: var(--color-rose);
  font-size: 12px;
  line-height: 1.4;
}
.opt {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
}
.opt .rk-checkbox {
  margin-top: 1px;
}
.otxt {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.otxt b {
  font-size: 12.5px;
  font-weight: 600;
}
.note {
  font: 10.5px/1.4 var(--font-mono);
  color: var(--color-dim);
}
.warns {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.warn {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 8px 10px;
  font-size: 11.5px;
  line-height: 1.4;
  border: 1px solid;
}
.warn.amber {
  color: oklch(0.8 0.15 75);
  border-color: color-mix(in oklch, oklch(0.8 0.15 75) 45%, transparent);
  background: color-mix(in oklch, oklch(0.8 0.15 75) 8%, transparent);
}
.warn.rose {
  color: var(--color-rose);
  border-color: color-mix(in oklch, var(--color-rose) 45%, transparent);
  background: color-mix(in oklch, var(--color-rose) 8%, transparent);
}
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--color-line-soft);
}
.keys {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.foot .btn {
  flex: none;
  white-space: nowrap;
}
.go {
  position: relative;
  background: var(--color-rose);
  border-color: var(--color-rose);
  color: var(--color-ember-ink);
  filter: drop-shadow(0 0 14px color-mix(in oklch, var(--color-rose) 50%, transparent));
  overflow: hidden;
}
.go:disabled {
  opacity: 0.45;
  background: var(--color-rose);
  border-color: var(--color-rose);
  color: var(--color-ember-ink);
  filter: none;
}
/* the hold fills from the left */
.go.holding::before {
  content: '';
  position: absolute;
  inset: 0;
  transform-origin: left;
  transform: scaleX(var(--held, 0));
  background: oklch(0 0 0 / 0.3);
  pointer-events: none;
}
.holdhint {
  color: var(--color-ember-ink);
  opacity: 0.7;
  text-transform: none;
  letter-spacing: 0;
}
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  background: oklch(0 0 0 / 0.85);
}
.lightbox img {
  max-width: calc(100% - 120px);
  max-height: calc(100% - 60px);
  object-fit: contain;
  box-shadow: 0 0 0 2px var(--color-rose);
}
.nav,
.lx {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: color-mix(in oklch, var(--color-surf) 70%, transparent);
  border: 1px solid var(--color-line);
  color: var(--color-tx);
}
.nav.prev {
  left: 16px;
}
.nav.next {
  right: 16px;
}
.lx {
  top: 16px;
  right: 16px;
}
.counter {
  position: absolute;
  bottom: 16px;
  color: var(--color-tx);
}
@media (prefers-reduced-motion: reduce) {
  .sheet {
    animation: none;
  }
}
</style>
