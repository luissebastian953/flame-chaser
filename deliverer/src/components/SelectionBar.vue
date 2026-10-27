<script setup lang="ts">
import type { DeleteMode } from '@/lib/types';

/**
 * The bar that replaces the gallery header while images are being chosen:
 * ×, the count, the mode pill (reopens the picker), the mode's own control
 * (any/all tags · Review only), Clear and Delete N. Under it, one hint line
 * that collapses after the first pick. Rose everywhere: rose means "marked
 * for deletion"; ember stays for filtering.
 */
const props = defineProps<{
  total: number;
  label: string;
  bySource: Record<string, number>;
  bytes?: number | null;
  /** Esc was pressed with a selection: the bar asks for a second Esc */
  leaving?: boolean;
}>();

const emit = defineEmits<{ close: []; delete: []; switch: [mode: DeleteMode] }>();
const del = useDeletion();
const fm = useFormats();
const { t } = useI18n();
const mode = computed(() => del.mode ?? 'image');

const counts = computed(() => {
  const set = del.selected;
  return {
    pixiv: props.bySource.pixiv ?? 0,
    x: props.bySource.twitter ?? 0,
    n: set.size,
  };
});

const of = computed(() =>
  mode.value === 'tag'
    ? t('gallery.delete.bar.ofTags', {
        tags: t('gallery.delete.bar.tagCount', { n: del.terms.length }, del.terms.length),
        pixiv: fm.number(counts.value.pixiv),
        x: fm.number(counts.value.x),
      })
    : mode.value === 'all'
      ? t('gallery.delete.bar.ofAll', {
          pixiv: fm.number(counts.value.pixiv),
          x: fm.number(counts.value.x),
          size: props.bytes == null ? '…' : fm.bytes(props.bytes),
        })
      : t('gallery.delete.bar.of', {
          total: fm.number(props.total),
          pixiv: fm.number(counts.value.pixiv),
          x: fm.number(counts.value.x),
        }),
);

const minus = computed(() =>
  del.mode !== 'image' && del.dropped.length
    ? t('gallery.delete.bar.minus', {
        n: fm.number(del.base.length),
        kept: fm.number(del.dropped.length),
        left: fm.number(del.count),
      })
    : '',
);
</script>

<template>
  <div class="selbar" role="toolbar" :aria-label="$t('gallery.delete.menu.title')">
    <div class="strip">
      <button class="btn gh x" :aria-label="$t('gallery.delete.bar.close')" @click="emit('close')">
        <Icon name="close" :size="14" />
      </button>
      <div class="count">
        <b>
          {{
            leaving
              ? $t('gallery.delete.bar.leaveConfirm')
              : $t('gallery.delete.bar.selected', { n: fm.number(del.count) }, del.count)
          }}
        </b>
        <span class="mono">{{ minus || of }}</span>
      </div>
      <DeleteMenu :pill="mode" :total="total" :label="label" @pick="(m) => emit('switch', m)" />
      <div v-if="mode === 'tag'" class="seg" role="group" :aria-label="$t('gallery.delete.bar.matchLabel')">
        <button
          class="btn sm"
          :class="{ on: del.match === 'any' }"
          :aria-pressed="del.match === 'any'"
          @click="del.setMatch('any')"
        >
          {{ $t('gallery.delete.bar.any') }}
        </button>
        <button
          class="btn sm"
          :class="{ on: del.match === 'all' }"
          :aria-pressed="del.match === 'all'"
          @click="del.setMatch('all')"
        >
          {{ $t('gallery.delete.bar.all') }}
        </button>
      </div>
      <button
        v-else-if="mode === 'smart'"
        class="btn sm gh"
        :class="{ on: del.reviewOnly }"
        :aria-pressed="del.reviewOnly"
        @click="del.reviewOnly = !del.reviewOnly"
      >
        <Icon name="eye" :size="12" />
        {{ $t('gallery.delete.bar.reviewOnly') }}
      </button>
      <div class="spacer" />
      <button class="btn gh sm" :disabled="!del.clearable" @click="del.clear()">
        {{ $t('gallery.delete.bar.clear') }}
      </button>
      <button class="btn del" :disabled="!del.count || del.busy" @click="emit('delete')">
        <Icon v-if="del.busy" name="loader" class="spin" :size="12" />
        <Icon v-else name="trash" :size="13" />
        {{ $t('gallery.delete.bar.delete', { n: fm.number(del.count) }) }}
      </button>
    </div>
    <Transition name="hint">
      <div v-if="!del.hintSeen" class="hint">
        <Icon
          :name="mode === 'image' ? 'image' : mode === 'tag' ? 'tag' : mode === 'smart' ? 'scan' : 'layers'"
          :size="14"
          class="hic"
        />
        <i18n-t v-if="mode === 'image'" keypath="gallery.delete.hint.image" tag="span" class="txt">
          <template #shift>
            <kbd>{{ $t('gallery.delete.hint.shift') }}</kbd>
          </template>
          <template #a>
            <kbd>{{ $t('gallery.delete.hint.a') }}</kbd>
          </template>
          <template #esc>
            <kbd>{{ $t('gallery.delete.hint.esc') }}</kbd>
          </template>
        </i18n-t>
        <span v-else class="txt">{{ $t(`gallery.delete.hint.${mode}`) }}</span>
        <span class="mono hides">{{ $t('gallery.delete.hint.hides') }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.selbar {
  position: relative;
  z-index: 3;
  /* a drag that starts on the bar must never paint a text selection over it */
  user-select: none;
  -webkit-user-select: none;
}
/* not `.bar`: that is the global progress bar, whose child divs fill ember */
.strip {
  position: relative;
  /* the blur makes the bar a stacking layer: lift it above the hint line so a
     picker opened from the mode pill is not painted underneath */
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 12px;
  /* as tall as the header it replaces: its 18/14px padding around a two-line
     title (17px + 11px at line-height 1.5) plus the hairline underneath */
  height: 75px;
  padding: 0 24px;
  /* a maroon tint on the left, fading to the plain plate by the middle. Mixed
     in sRGB on purpose: in OKLCH rose (hue 12) and the navy plate (hue 265)
     interpolate through purple */
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--color-rose) 22%, color-mix(in srgb, var(--color-surf) 60%, transparent) 78%),
    color-mix(in srgb, var(--color-surf) 60%, transparent) 50%
  );
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  white-space: nowrap;
}
/* the 2px rose rule along the bottom edge, glowing both ways; clipped at the
   sides only so the glow never bleeds onto the rail */
.strip::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--color-rose);
  box-shadow:
    0 0 10px var(--color-rose),
    0 0 24px color-mix(in oklch, var(--color-rose) 70%, transparent);
  clip-path: inset(-30px 0 -30px 0);
  pointer-events: none;
}
/* the 28px fall-off beneath the rule */
.strip::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  height: 28px;
  background: linear-gradient(
    to bottom,
    color-mix(in oklch, var(--color-rose) 28%, transparent),
    transparent
  );
  pointer-events: none;
}
.strip > * {
  flex: none;
}
/* the standard ghost button, the same 34px square as the header's back chevron */
.x {
  width: 34px;
  height: 34px;
  padding: 0;
  justify-content: center;
}
.x:hover {
  color: var(--color-rose);
  border-color: var(--color-rose);
}
.count {
  display: flex;
  align-items: baseline;
  gap: 9px;
}
.count b {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-rose);
}
.mono {
  font: 11px var(--font-mono);
  color: var(--color-dim);
}
.seg {
  display: flex;
  gap: 1px;
  padding: 2px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
}
.seg .btn {
  height: 23px;
  border: 0;
  background: transparent;
  color: var(--color-mut);
  clip-path: none;
}
/* the chosen combination is a focus, so it stays ember like every other toggle */
.seg .btn.on {
  background: color-mix(in oklch, var(--color-ember) 22%, var(--color-bg));
  color: var(--color-ember);
}
.btn.del {
  background: var(--color-rose);
  border-color: var(--color-rose);
  color: var(--color-ember-ink);
  font-weight: 600;
  filter: drop-shadow(0 0 18px color-mix(in oklch, var(--color-rose) 55%, transparent));
}
.btn.del:disabled {
  filter: none;
}
.hint {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  height: 48px;
  padding: 14px 24px 0;
  /* no plate of its own: the rule's fall-off above is the only colour here */
  border-bottom: 1px solid var(--color-line-soft);
  font-size: 12px;
  color: var(--color-tx);
  overflow: hidden;
}
.hic {
  flex: none;
  color: var(--color-rose);
  margin-top: 1px;
}
.txt {
  flex: 1;
  min-width: 0;
}
kbd {
  font: 10.5px var(--font-mono);
  padding: 1px 5px;
  border: 1px solid var(--color-line);
  background: var(--color-surf2);
}
.hides {
  flex: none;
}
.hint-enter-active,
.hint-leave-active {
  transition:
    height 0.18s ease-out,
    padding 0.18s ease-out,
    opacity 0.18s ease-out;
}
.hint-enter-from,
.hint-leave-to {
  height: 0;
  padding-top: 0;
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .hint-enter-active,
  .hint-leave-active {
    transition: none;
  }
}
</style>
