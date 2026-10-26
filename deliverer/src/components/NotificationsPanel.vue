<script setup lang="ts">
import type { BackgroundMode } from '@/stores/background';

/**
 * Settings › Notifications: what Curio shows while it crawls and another
 * app is in front. One dropdown -- mini window, one notification per
 * finished run, or nothing -- and the mini window's two sub-options.
 * Where a floating window cannot exist (Linux Wayland, the browser build)
 * the mini window row is dimmed and a note says why.
 */
const bg = useBackground();

const MODE_ICON: Record<BackgroundMode, string> = { mini: 'monitor', notify: 'bell', none: 'eye-off' };

const mode = computed({
  get: () => bg.mode,
  set: (v: BackgroundMode) => bg.set({ mode: v }),
});

const miniBlocked = computed(() => bg.supported === false);

const startExpanded = computed({
  get: () => bg.startExpanded,
  set: (v: boolean) => bg.set({ startExpanded: v }),
});

const trayKeeps = computed({
  get: () => bg.trayKeepsProgress,
  set: (v: boolean) => bg.set({ trayKeepsProgress: v }),
});

onMounted(() => {
  if (bg.supported === null) bg.probe();
});
</script>

<template>
  <div class="panel flex-1">
    <div class="phead">
      <span class="ptitle">{{ $t('settings.notifications.title') }}</span>
      <span class="data text-small text-dim ml-10">{{ $t('settings.notifications.sub') }}</span>
    </div>
    <div class="p-15 flex flex-col gap-15">
      <div class="field w-[420px] max-w-full">
        <SelectRoot v-model="mode">
          <SelectTrigger class="btn gh rk-select-trigger trig">
            <span class="flex items-center gap-10 min-w-0">
              <Icon :name="MODE_ICON[bg.mode]" :size="13" />
              <SelectValue />
            </span>
            <Icon name="chevron-down" :size="14" class="text-dim" />
          </SelectTrigger>
          <SelectPortal>
            <SelectContent class="rk-select-content" position="popper" :side-offset="4">
              <SelectViewport>
                <SelectItem
                  v-for="m in ['mini', 'notify', 'none'] as BackgroundMode[]"
                  :key="m"
                  :value="m"
                  :disabled="m === 'mini' && miniBlocked"
                  class="rk-select-item opt"
                >
                  <Icon :name="MODE_ICON[m]" :size="13" class="oi" />
                  <span class="ot">
                    <SelectItemText>{{ $t(`settings.notifications.mode.${m}.label`) }}</SelectItemText>
                    <span class="od">
                      {{
                        m === 'mini' && miniBlocked
                          ? bg.reason === 'browser'
                            ? $t('settings.notifications.browserOnly')
                            : $t('settings.notifications.miniUnsupported')
                          : $t(`settings.notifications.mode.${m}.desc`)
                      }}
                    </span>
                  </span>
                  <SelectItemIndicator class="oc">
                    <Icon name="check" :size="13" />
                  </SelectItemIndicator>
                </SelectItem>
              </SelectViewport>
            </SelectContent>
          </SelectPortal>
        </SelectRoot>
        <div class="hint">
          {{
            bg.effectiveMode === 'mini'
              ? $t('settings.notifications.miniHint')
              : bg.effectiveMode === 'notify'
                ? $t('settings.notifications.notifyHint')
                : $t('settings.notifications.noneHint')
          }}
        </div>
      </div>

      <div class="grid grid-cols-2 gap-15" :class="{ off: bg.effectiveMode !== 'mini' }">
        <label class="opt-row">
          <CheckboxRoot
            :model-value="startExpanded"
            :disabled="bg.effectiveMode !== 'mini'"
            class="rk-checkbox"
            @update:model-value="(v) => (startExpanded = v === true)"
          />
          <span>
            <span class="ttl">{{ $t('settings.notifications.startExpanded') }}</span>
            <span class="hint">{{ $t('settings.notifications.startExpandedHint') }}</span>
          </span>
        </label>
        <label class="opt-row">
          <CheckboxRoot
            :model-value="trayKeeps"
            :disabled="bg.effectiveMode !== 'mini'"
            class="rk-checkbox"
            @update:model-value="(v) => (trayKeeps = v === true)"
          />
          <span>
            <span class="ttl">{{ $t('settings.notifications.trayKeeps') }}</span>
            <span class="hint">{{ $t('settings.notifications.trayKeepsHint') }}</span>
          </span>
        </label>
      </div>

      <div v-if="bg.coerced && bg.reason === 'wayland'" class="note">
        <Icon name="warning" :size="13" />
        <i18n-t keypath="settings.notifications.coerced" tag="span">
          <template #mini>
            <b>{{ $t('settings.notifications.mode.mini.label') }}</b>
          </template>
          <template #notify>
            <b>{{ $t('settings.notifications.mode.notify.label') }}</b>
          </template>
        </i18n-t>
      </div>
      <div v-else-if="bg.reason === 'browser'" class="note">
        <Icon name="info" :size="13" />
        <span>{{ $t('settings.notifications.browserNote') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trig {
  width: 100%;
  justify-content: space-between;
}
.opt {
  display: grid;
  grid-template-columns: 16px 1fr 16px;
  gap: 10px;
  align-items: start;
  padding: 8px 10px;
}
.opt[data-disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}
.opt[data-state='checked'] {
  background: color-mix(in oklch, var(--ember) 12%, transparent);
}
.oi {
  margin-top: 2px;
}
.ot {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.ot :deep([data-radix-select-item-text]),
.ot :first-child {
  font-size: 12.5px;
  color: var(--tx);
}
.od {
  font: 400 10.5px var(--font-mono);
  color: var(--dim);
  white-space: normal;
}
.oc {
  color: var(--ember);
  margin-top: 2px;
}
.opt-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.opt-row > span {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.ttl {
  font-size: 13px;
}
.off {
  opacity: 0.5;
}
.off .opt-row {
  cursor: default;
}
.note {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  border: 1px solid color-mix(in oklch, oklch(0.8 0.15 75) 55%, transparent);
  color: var(--mut);
  font: 400 12px/1.5 var(--font-mono);
}
.note > svg {
  flex: none;
  margin-top: 2px;
  color: oklch(0.8 0.15 75);
}
.note b {
  color: var(--tx);
}
</style>
