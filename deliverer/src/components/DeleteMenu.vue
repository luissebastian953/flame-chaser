<script setup lang="ts">
import type { DeleteMode } from '@/lib/types';

/**
 * Delete ▾ and its mode picker: four ways to choose images (by image, by
 * tag, Smart, All), 1–4 or ↑↓ to move, ⏎ to enter, Esc closes. Nothing
 * happens until a mode is picked. Delete character is not a mode -- it lives
 * in the header's more menu, and the footer says so.
 */
const props = defineProps<{
  /** every image the character has (the All row's count) */
  total: number;
  label: string;
  /** Smart candidates the daemon already counted, when known */
  suggested?: number | null;
  /** rendered as the bar's mode pill instead of the header button */
  pill?: DeleteMode | null;
}>();

const emit = defineEmits<{ pick: [mode: DeleteMode] }>();
const fm = useFormats();
const open = ref(false);
const highlight = ref(0);
const panel = ref<HTMLElement | null>(null);
const MODES: DeleteMode[] = ['image', 'tag', 'smart', 'all'];
const ICONS: Record<DeleteMode, string> = { image: 'image', tag: 'tag', smart: 'scan', all: 'layers' };

function toggle() {
  open.value = !open.value;
  if (open.value) {
    // opened from the bar: start on the mode that is already active
    highlight.value = props.pill ? MODES.indexOf(props.pill) : 0;
    nextTick(() => panel.value?.focus());
  }
}

function pick(mode: DeleteMode) {
  open.value = false;
  emit('pick', mode);
}

function onKey(e: KeyboardEvent) {
  const n = Number(e.key);
  if (n >= 1 && n <= 4) {
    e.preventDefault();
    highlight.value = n - 1;
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    highlight.value = (highlight.value + (e.key === 'ArrowDown' ? 1 : 3)) % 4;
  } else if (e.key === 'Enter') {
    e.preventDefault();
    pick(MODES[highlight.value]!);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    open.value = false;
  }
}

function onDocClick(e: MouseEvent) {
  if (open.value && !(e.target as HTMLElement).closest('.dmenu')) open.value = false;
}

onMounted(() => document.addEventListener('mousedown', onDocClick));
onUnmounted(() => document.removeEventListener('mousedown', onDocClick));
</script>

<template>
  <div class="dmenu">
    <button
      v-if="pill"
      class="btn sm pillbtn"
      :aria-expanded="open"
      :aria-label="$t('gallery.delete.bar.switchMode')"
      @click="toggle"
    >
      {{ $t(`gallery.delete.bar.mode.${pill}`) }}
      <Icon name="chevron-down" :size="12" />
    </button>
    <button v-else class="btn danger trigger" :aria-expanded="open" @click="toggle">
      <Icon name="trash" :size="13" />
      {{ $t('gallery.delete.menu.button') }}
      <Icon name="chevron-down" :size="12" />
    </button>
    <Transition name="pop">
      <div
        v-if="open"
        ref="panel"
        class="picker"
        :class="{ frompill: !!pill }"
        role="menu"
        tabindex="-1"
        @keydown="onKey"
      >
        <div class="head">
          <span class="ptitle rose">{{ $t('gallery.delete.menu.title') }}</span>
          <span class="mono dim">{{ $t('gallery.delete.menu.sub') }}</span>
        </div>
        <button
          v-for="(mode, i) in MODES"
          :key="mode"
          class="row"
          :class="{ hl: highlight === i, all: mode === 'all', cur: pill === mode }"
          role="menuitemradio"
          :aria-checked="pill === mode"
          @mouseenter="highlight = i"
          @click="pick(mode)"
        >
          <span class="ib"><Icon :name="ICONS[mode]" :size="14" /></span>
          <span class="txt">
            <span class="ttl">
              {{
                mode === 'all'
                  ? $t('gallery.delete.menu.all.title', { n: fm.number(total) })
                  : $t(`gallery.delete.menu.${mode}.title`)
              }}
              <kbd>{{ i + 1 }}</kbd>
              <Icon v-if="pill === mode" name="check" :size="12" class="cur-mark" />
              <span v-if="mode === 'smart' && suggested" class="chip amber">
                {{ $t('gallery.delete.menu.smart.suggested', { n: suggested }) }}
              </span>
            </span>
            <span class="desc">
              {{
                mode === 'all'
                  ? $t('gallery.delete.menu.all.desc', { label })
                  : $t(`gallery.delete.menu.${mode}.desc`)
              }}
            </span>
          </span>
        </button>
        <div class="foot">
          <span>{{ $t('gallery.delete.menu.foot', { days: 30 }) }}</span>
          <span class="cyan">{{ $t('gallery.delete.menu.character') }}</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dmenu {
  position: relative;
  flex: none;
}
.trigger {
  background: transparent;
  border-color: var(--color-rose);
}
.pillbtn {
  border-color: var(--color-rose);
  color: var(--color-rose);
  background: transparent;
}
.picker {
  --cut: 10px;
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 30;
  width: 372px;
  background: color-mix(in oklch, var(--color-surf) 86%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  backdrop-filter: blur(14px) saturate(1.2);
  border: 1px solid var(--color-line);
  border-left: 2px solid var(--color-rose);
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
  filter: drop-shadow(0 14px 40px oklch(0 0 0 / 0.5))
    drop-shadow(0 0 18px color-mix(in oklch, var(--color-rose) 25%, transparent));
  outline: none;
  text-align: left;
  white-space: normal; /* the bar is nowrap; the descriptions must wrap */
}
/* under the bar's mode pill the picker hangs from its left edge, not the right */
.picker.frompill {
  left: 0;
  right: auto;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 12px 16px 9px;
  border-bottom: 1px solid var(--color-line-soft);
}
.rose {
  color: var(--color-rose);
}
.dim {
  color: var(--color-dim);
}
.mono {
  font: 11px var(--font-mono);
}
.row {
  display: flex;
  gap: 12px;
  width: 100%;
  padding: 11px 16px;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--color-line-soft);
  color: var(--color-tx);
  text-align: left;
  cursor: pointer;
}
.row.hl {
  background: color-mix(in oklch, var(--color-rose) 10%, transparent);
}
/* the mode already active, when the picker opens from the bar's pill */
.row.cur .ib {
  background: color-mix(in srgb, var(--color-rose) 18%, transparent);
  border-color: var(--color-rose);
}
.cur-mark {
  margin-left: auto;
  color: var(--color-rose);
}
.ib {
  flex: none;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-line);
  color: var(--color-rose);
}
.row.all .ib {
  border-color: var(--color-rose);
}
.txt {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.ttl {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
}
.row.all .ttl {
  color: var(--color-rose);
}
kbd {
  font: 10px var(--font-mono);
  padding: 1px 5px;
  border: 1px solid var(--color-line);
  color: var(--color-dim);
}
.desc {
  font: 11px/1.4 var(--font-mono);
  color: var(--color-dim);
  white-space: normal;
  overflow-wrap: anywhere;
}
.chip.amber {
  height: 18px;
  padding: 0 6px;
  font-size: 10px;
  background: transparent;
  border-color: oklch(0.8 0.15 75);
  color: oklch(0.8 0.15 75);
}
.foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 10px;
  padding: 9px 16px 11px;
  font: 10.5px var(--font-mono);
  color: var(--color-dim);
}
.cyan {
  color: var(--color-cyan);
}
.pop-enter-active,
.pop-leave-active {
  transition:
    opacity 0.14s ease-out,
    transform 0.14s ease-out;
}
.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (prefers-reduced-motion: reduce) {
  .pop-enter-active,
  .pop-leave-active {
    transition: none;
  }
}
</style>
