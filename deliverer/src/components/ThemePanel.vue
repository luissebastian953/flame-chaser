<script setup lang="ts">
/**
 * Settings › Theme. Edits the store's DRAFT: presets, the custom theme
 * (colours and finishes), how the window sits on the desktop, and the Live
 * preview beside it. Nothing reaches the app until Apply (the Settings
 * header), which promotes the draft; Reset to default drafts and applies
 * the board defaults.
 */
import type { Corners, Glow } from '@/stores/theme';

const theme = useTheme();
const src = useSources();
const { t } = useI18n();

const CORNERS: Corners[] = ['cut', 'square', 'round'];
const GLOWS: Glow[] = ['off', 'soft', 'neon'];
const COLORS = ['primary', 'accent', 'bg', 'surface'] as const;

type ColorKey = (typeof COLORS)[number];

const COLOR_LABEL: Record<ColorKey, string> = {
  primary: 'settings.theme.custom.primary',
  accent: 'settings.theme.custom.accent',
  bg: 'settings.theme.custom.background',
  surface: 'settings.theme.custom.surface',
};

// hex fields: the text is free to be half-typed; only a full hex reaches the draft
const hexDraft = reactive<Record<ColorKey, string>>({
  primary: theme.draft.theme.primary,
  accent: theme.draft.theme.accent,
  bg: theme.draft.theme.bg,
  surface: theme.draft.theme.surface,
});

watch(
  () => COLORS.map((k) => theme.draft.theme[k]),
  (vals) => COLORS.forEach((k, i) => (hexDraft[k] = vals[i]!)),
);

function typed(k: ColorKey, v: string) {
  hexDraft[k] = v;
  const hex = v.startsWith('#') ? v : `#${v}`;
  if (/^#[0-9a-f]{6}$/i.test(hex)) theme.draft.theme[k] = hex.toLowerCase();
}

// Reka sliders take number[]
const scan = computed({
  get: () => [theme.draft.theme.scanlines],
  set: (v) => (theme.draft.theme.scanlines = v[0] ?? 0),
});

const opacity = computed({
  get: () => [theme.draft.window.opacity],
  set: (v) => (theme.draft.window.opacity = v[0] ?? 1),
});

const blurPx = computed({
  get: () => [theme.draft.window.blurPx],
  set: (v) => (theme.draft.window.blurPx = v[0] ?? 0),
});

const grid = computed({
  get: () => [theme.draft.gridAlpha],
  set: (v) => (theme.draft.gridAlpha = v[0] ?? 0.035),
});

const basedOn = computed({
  get: () => theme.draft.theme.basedOn,
  set: (id: string) => theme.pick(id),
});

// import / export: the clipboard, so it works in the window and the browser
const note = ref('');
let noteTimer: ReturnType<typeof setTimeout> | undefined;

function say(key: string) {
  note.value = t(key);
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => (note.value = ''), 3000);
}

async function exportJson() {
  try {
    await navigator.clipboard.writeText(theme.exportJson());
    say('settings.theme.custom.copied');
  } catch {
    importing.value = true;
    pasted.value = theme.exportJson(); // no clipboard: show it to copy by hand
  }
}

const importing = ref(false);
const pasted = ref('');

function load() {
  if (theme.importJson(pasted.value)) {
    importing.value = false;
    pasted.value = '';
  } else {
    say('settings.theme.custom.badJson');
  }
}

function savePreset() {
  theme.saveAsPreset();
  say('settings.theme.custom.saved');
}

const previewMeta = computed(() => {
  const w = theme.draft.window;
  const name = theme.draft.theme.name;
  return w.transparent
    ? t('settings.theme.preview.meta', {
        name,
        opacity: Math.round(w.opacity * 100),
        blur: w.blur ? w.blurPx : 0,
      })
    : t('settings.theme.preview.solid', { name });
});
</script>

<template>
  <div class="theme-grid">
    <div class="col">
      <div class="panel">
        <div class="phead">
          <span class="ptitle">{{ $t('settings.theme.title') }}</span>
          <span class="kv">{{ $t('settings.theme.intro') }}</span>
          <div class="spacer" />
          <span v-if="note" class="kv note">{{ note }}</span>
          <span v-else-if="theme.dirty" class="kv">{{ $t('settings.theme.unsaved') }}</span>
        </div>
        <div class="p-15 flex flex-col gap-15">
          <div class="field">
            <label>{{ $t('settings.theme.presets') }}</label>
            <div class="presets">
              <button
                v-for="p in theme.presets"
                :key="p.id"
                type="button"
                class="preset"
                :class="{ on: theme.draft.theme.basedOn === p.id }"
                :style="{ '--p-bg': p.bg, '--p-surf': p.surface, '--p-pri': p.primary, '--p-acc': p.accent }"
                @click="theme.pick(p.id)"
              >
                <span class="thumb" aria-hidden="true">
                  <i class="plate" />
                  <i class="pri" />
                  <i class="acc" />
                </span>
                <b>{{ p.name }}</b>
                <span class="tag">{{ p.builtIn ? p.tagline : $t('settings.theme.userPreset') }}</span>
                <span class="swatches" aria-hidden="true">
                  <i :style="{ background: p.bg }" />
                  <i :style="{ background: p.surface }" />
                  <i :style="{ background: p.primary }" />
                  <i :style="{ background: p.accent }" />
                </span>
                <span
                  v-if="!p.builtIn"
                  class="rm"
                  role="button"
                  :title="$t('settings.theme.removePreset')"
                  :aria-label="$t('settings.theme.removePreset')"
                  @click.stop="theme.removePreset(p.id)"
                >
                  <Icon name="close" :size="10" />
                </span>
              </button>
            </div>
          </div>

          <div class="phead inner">
            <span class="ptitle">{{ $t('settings.theme.custom.title') }}</span>
            <span class="kv">{{ $t('settings.theme.custom.hint') }}</span>
            <div class="spacer" />
            <button class="linkish" type="button" @click="importing = !importing">
              {{ $t('settings.theme.custom.import') }}
            </button>
          </div>
          <div v-if="importing" class="field">
            <label>{{ $t('settings.theme.custom.importHint') }}</label>
            <textarea v-model="pasted" class="paste mono" rows="5" spellcheck="false" />
            <div class="flex gap-6">
              <button class="btn sm pri" type="button" @click="load">
                {{ $t('settings.theme.custom.load') }}
              </button>
              <button class="btn sm gh" type="button" @click="importing = false">
                {{ $t('settings.theme.custom.cancel') }}
              </button>
            </div>
          </div>

          <div class="two">
            <div class="field">
              <label for="theme-name">{{ $t('settings.theme.custom.name') }}</label>
              <input
                id="theme-name"
                v-model="theme.draft.theme.name"
                class="in"
                :placeholder="$t('settings.theme.custom.namePlaceholder')"
                maxlength="40"
              />
            </div>
            <div class="field">
              <label>{{ $t('settings.theme.custom.basedOn') }}</label>
              <SelectRoot v-model="basedOn">
                <SelectTrigger
                  class="btn gh rk-select-trigger based"
                  :aria-label="$t('settings.theme.custom.basedOn')"
                >
                  <SelectValue>{{ theme.basePreset?.name ?? theme.draft.theme.basedOn }}</SelectValue>
                  <Icon name="chevron-down" :size="14" class="text-dim" />
                </SelectTrigger>
                <SelectPortal>
                  <SelectContent class="rk-select-content" position="popper" :side-offset="4">
                    <SelectViewport>
                      <SelectItem v-for="p in theme.presets" :key="p.id" :value="p.id" class="rk-select-item">
                        <SelectItemText>{{ p.name }}</SelectItemText>
                      </SelectItem>
                    </SelectViewport>
                  </SelectContent>
                </SelectPortal>
              </SelectRoot>
            </div>
          </div>

          <div class="four">
            <div v-for="k in COLORS" :key="k" class="field">
              <label :for="`theme-${k}`">{{ $t(COLOR_LABEL[k]) }}</label>
              <div class="hex">
                <input
                  :value="theme.draft.theme[k]"
                  type="color"
                  class="sw"
                  :aria-label="$t(COLOR_LABEL[k])"
                  @input="typed(k, ($event.target as HTMLInputElement).value)"
                />
                <input
                  :id="`theme-${k}`"
                  :value="hexDraft[k]"
                  class="in mono"
                  maxlength="7"
                  spellcheck="false"
                  @input="typed(k, ($event.target as HTMLInputElement).value)"
                />
              </div>
            </div>
          </div>

          <div class="finish">
            <div class="field">
              <label>{{ $t('settings.theme.custom.corners') }}</label>
              <div class="seg" role="group">
                <button
                  v-for="c in CORNERS"
                  :key="c"
                  type="button"
                  class="btn sm"
                  :class="{ on: theme.draft.theme.corners === c }"
                  :aria-pressed="theme.draft.theme.corners === c"
                  @click="theme.draft.theme.corners = c"
                >
                  {{ $t(`settings.theme.custom.cornersOf.${c}`) }}
                </button>
              </div>
            </div>
            <div class="field">
              <label>{{ $t('settings.theme.custom.glow') }}</label>
              <div class="seg" role="group">
                <button
                  v-for="g in GLOWS"
                  :key="g"
                  type="button"
                  class="btn sm"
                  :class="{ on: theme.draft.theme.glow === g }"
                  :aria-pressed="theme.draft.theme.glow === g"
                  @click="theme.draft.theme.glow = g"
                >
                  {{ $t(`settings.theme.custom.glowOf.${g}`) }}
                </button>
              </div>
            </div>
            <div class="field grow">
              <label>
                {{ $t('settings.theme.custom.scanlines') }}
                <span class="data text-tx ml-5">
                  {{ $t('settings.theme.percent', { n: Math.round(theme.draft.theme.scanlines * 100) }) }}
                </span>
              </label>
              <SliderRoot v-model="scan" :min="0" :max="1" :step="0.05" class="rk-slider">
                <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
                <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.custom.scanAria')" />
              </SliderRoot>
            </div>
          </div>

          <div class="flex gap-6 justify-end">
            <button class="btn gh sm" type="button" @click="exportJson">
              {{ $t('settings.theme.custom.export') }}
            </button>
            <button class="btn sm" type="button" @click="savePreset">
              {{ $t('settings.theme.custom.save') }}
            </button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="phead">
          <span class="ptitle">{{ $t('settings.theme.window.title') }}</span>
          <span class="kv">{{ $t('settings.theme.window.hint') }}</span>
        </div>
        <div class="p-15 flex flex-col gap-15">
          <div class="opt">
            <CheckboxRoot id="win-transparent" v-model="theme.draft.window.transparent" class="rk-checkbox" />
            <div class="grow">
              <label for="win-transparent" class="lbl">{{ $t('settings.theme.window.transparent') }}</label>
              <div class="hint">{{ $t('settings.theme.window.transparentHint') }}</div>
              <div class="flex items-center gap-10 mt-10">
                <SliderRoot
                  v-model="opacity"
                  :min="0.3"
                  :max="1"
                  :step="0.01"
                  :disabled="!theme.draft.window.transparent"
                  class="rk-slider grow"
                >
                  <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
                  <SliderThumb
                    class="rk-slider-thumb"
                    :aria-label="$t('settings.theme.window.opacityAria')"
                  />
                </SliderRoot>
                <span class="data w-40 text-right">
                  {{ $t('settings.theme.percent', { n: Math.round(theme.draft.window.opacity * 100) }) }}
                </span>
              </div>
            </div>
          </div>
          <div class="opt">
            <CheckboxRoot
              id="win-blur"
              v-model="theme.draft.window.blur"
              class="rk-checkbox"
              :disabled="!theme.draft.window.transparent"
            />
            <div class="grow">
              <label for="win-blur" class="lbl">{{ $t('settings.theme.window.blur') }}</label>
              <div class="hint">{{ $t('settings.theme.window.blurHint') }}</div>
              <div v-if="!src.inTauri" class="hint">{{ $t('settings.theme.window.desktopOnly') }}</div>
              <div class="flex items-center gap-10 mt-10">
                <SliderRoot
                  v-model="blurPx"
                  :min="0"
                  :max="24"
                  :step="1"
                  :disabled="!theme.draft.window.transparent"
                  class="rk-slider grow"
                >
                  <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
                  <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.window.blurAria')" />
                </SliderRoot>
                <span class="data w-40 text-right">
                  {{ $t('settings.theme.px', { n: theme.draft.window.blurPx }) }}
                </span>
              </div>
            </div>
          </div>
          <div class="field">
            <label>
              {{ $t('settings.theme.window.grid') }}
              <span class="data text-tx ml-5">
                {{ $t('settings.theme.percent', { n: Math.round(theme.draft.gridAlpha * 100) }) }}
              </span>
            </label>
            <SliderRoot v-model="grid" :min="0" :max="0.15" :step="0.005" class="rk-slider">
              <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
              <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.window.gridAria')" />
            </SliderRoot>
          </div>
        </div>
      </div>
    </div>

    <div class="panel side">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.theme.preview.title') }}</span>
        <div class="spacer" />
        <span class="kv mono">{{ previewMeta }}</span>
      </div>
      <ThemePreview />
      <div class="hint p-15 pt-0">{{ $t('settings.theme.preview.hint') }}</div>
    </div>
  </div>
</template>

<style scoped>
.theme-grid {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
  align-items: start;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.side {
  position: sticky;
  top: 0;
}
.note {
  color: var(--color-moss);
}
.phead.inner {
  margin: 0 -15px;
  border-top: 1px solid var(--color-line-soft);
}
.linkish {
  background: none;
  border: none;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-cyan);
  cursor: pointer;
}

/* presets: a mini plate drawn in the preset's own colours */
.presets {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: 8px;
}
.preset {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 8px 10px 9px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
  color: var(--color-tx);
  text-align: left;
  cursor: pointer;
}
.preset:hover {
  border-color: var(--color-mut);
}
.preset.on {
  border-color: var(--color-ember);
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--color-ember) 35%, transparent);
}
.preset b {
  font-size: 13px;
  font-weight: 600;
  margin-top: 4px;
}
.preset .tag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.thumb {
  position: relative;
  width: 100%;
  height: 46px;
  background: var(--p-bg);
  overflow: hidden;
}
.thumb .plate {
  position: absolute;
  left: 30%;
  top: 22%;
  width: 52%;
  height: 62%;
  background: var(--p-surf);
  border: 1px solid color-mix(in oklch, var(--p-surf) 80%, white);
}
.thumb .pri {
  position: absolute;
  left: 42%;
  top: 34%;
  width: 28%;
  height: 20%;
  background: var(--p-pri);
  box-shadow: 0 0 8px var(--p-pri);
}
.thumb .acc {
  position: absolute;
  left: 36%;
  bottom: 14%;
  width: 46%;
  height: 4px;
  background: var(--p-acc);
}
.swatches {
  display: flex;
  gap: 3px;
  margin-top: 4px;
}
.swatches i {
  width: 14px;
  height: 14px;
  border: 1px solid var(--color-line);
}
.rm {
  position: absolute;
  top: 4px;
  right: 4px;
  display: inline-flex;
  padding: 3px;
  color: var(--color-dim);
}
.rm:hover {
  color: var(--color-rose);
}

.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.four {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
.in {
  height: 32px;
  padding: 0 10px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
  color: var(--color-tx);
  font-size: 12.5px;
  width: 100%;
  min-width: 0;
}
.in:focus {
  outline: none;
  border-color: var(--color-ember);
}
.hex {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 6px 0 7px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
}
.hex .in {
  border: none;
  background: transparent;
  padding: 0;
  height: 100%;
  font-size: 12px;
}
.sw {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid var(--color-line);
  background: none;
  cursor: pointer;
}
.sw::-webkit-color-swatch-wrapper {
  padding: 0;
}
.sw::-webkit-color-swatch {
  border: none;
}
.based {
  width: 100%;
  justify-content: space-between;
}
.paste {
  width: 100%;
  padding: 8px 10px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
  color: var(--color-tx);
  font-size: 11px;
  resize: vertical;
}
.finish {
  display: flex;
  align-items: flex-end;
  gap: 14px;
}
.finish .grow {
  flex: 1;
  min-width: 140px;
}
.seg {
  display: inline-flex;
  gap: 1px;
  padding: 2px;
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
}
.seg .btn {
  height: 26px;
  border: 0;
  background: transparent;
  color: var(--color-mut);
  clip-path: none;
}
.seg .btn.on {
  background: color-mix(in oklch, var(--color-ember) 22%, var(--color-bg));
  color: var(--color-ember);
}
.opt {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.opt .lbl {
  font-size: 13px;
  font-weight: 500;
}
.grow {
  flex: 1;
  min-width: 0;
}
.rk-slider[data-disabled] {
  opacity: 0.4;
}
@media (max-width: 1200px) {
  .theme-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .side {
    position: static;
  }
}
</style>
