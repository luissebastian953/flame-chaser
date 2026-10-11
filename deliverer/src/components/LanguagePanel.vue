<script setup lang="ts">
/**
 * Settings › Language: interface language (or follow the system), how far
 * each translation has come, and the number/date/size formats — those are
 * independent of the language on purpose.
 */
import { LOCALES, coverage, savedChoice, setLocale, systemLocale, type LocaleCode } from '@/i18n';
import { REGIONS } from '@/stores/formats';

const fm = useFormats();

const choice = ref<LocaleCode | 'system'>(savedChoice());
const system = systemLocale();
const systemEntry = LOCALES.find((l) => l.code === system)!;
const follow = computed(() => choice.value === 'system');
/** The row that carries the check: the explicit pick, or what the system resolves to. */
const highlighted = computed(() => (choice.value === 'system' ? system : choice.value));

function pick(code: LocaleCode) {
  choice.value = code;
  setLocale(code);
}

function setFollow(on: boolean | 'indeterminate') {
  choice.value = on === true ? 'system' : highlighted.value;
  setLocale(choice.value);
}

const rows = coverage();

const CONTRIBUTE = 'https://github.com/luissebastian953/flame-chaser/tree/master/deliverer/src/locales';

const link = (u: string) =>
  import('@tauri-apps/plugin-opener').then((m) => m.openUrl(u)).catch(() => window.open(u));

// ---- formats ----
const regionKey = (code: string) => code.replace('-', '_');
const systemTag = navigator.language || 'en-US';
const now = new Date();

const preview = computed(() => ({
  number: fm.number(1234567.89),
  date: fm.date(now),
  dateTime: fm.date(now, true),
  size: fm.bytes(1536 * 1024 * 1024),
}));

watch(
  () => [fm.region, fm.dateStyle, fm.hour12, fm.sizeUnit],
  () => fm.persist(),
);
</script>

<template>
  <div class="flex flex-col gap-15 flex-1">
    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.language.title') }}</span>
        <div class="spacer" />
        <span class="data text-small text-dim">{{ $t('settings.language.interfaceHint') }}</span>
      </div>
      <div class="p-15 flex flex-col gap-15">
        <div class="field">
          <label>{{ $t('settings.language.interface') }}</label>
          <div class="langs">
            <button
              v-for="l in LOCALES"
              :key="l.code"
              class="lang"
              :class="{ on: highlighted === l.code, soon: !l.ready }"
              :disabled="!l.ready"
              @click="pick(l.code)"
            >
              <span class="native" :class="{ jp: l.code === 'ja' || l.code === 'zh' }">{{ l.native }}</span>
              <span class="data text-small text-dim">{{ l.label }}</span>
              <span class="spacer" />
              <span v-if="!l.ready" class="chip off">{{ $t('settings.language.soon') }}</span>
              <Icon v-else-if="highlighted === l.code" name="check" class="check" :size="16" />
            </button>
          </div>
        </div>

        <div class="flex items-center gap-10">
          <CheckboxRoot id="follow" :model-value="follow" class="rk-checkbox" @update:model-value="setFollow">
            <CheckboxIndicator />
          </CheckboxRoot>
          <label for="follow" class="text-small">
            {{ $t('settings.language.followSystem') }}
            <span class="hint ml-5">
              {{
                systemEntry.ready
                  ? $t('settings.language.systemIs', { name: systemEntry.native })
                  : $t('settings.language.systemNotReady', { name: systemEntry.native })
              }}
            </span>
          </label>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.language.coverage.title') }}</span>
        <span class="data text-small text-dim ml-10">{{ $t('settings.language.coverage.sub') }}</span>
        <div class="spacer" />
        <button class="btn gh sm" @click="link(CONTRIBUTE)">
          <Icon name="external" :size="13" />
          {{ $t('settings.language.coverage.contribute') }}
        </button>
      </div>
      <div class="p-15 flex flex-col gap-12">
        <div v-for="r in rows" :key="r.code" class="cov">
          <span class="native" :class="{ jp: r.code === 'ja' || r.code === 'zh' }">{{ r.native }}</span>
          <span class="data text-small text-dim">{{ r.label }}</span>
          <div class="bar"><div :style="{ width: r.pct + '%' }" /></div>
          <span class="data text-small pct">{{ r.pct }}%</span>
          <span class="data text-small text-dim keys">
            {{ $t('settings.language.coverage.keys', { translated: r.translated, total: r.total }) }}
          </span>
          <span class="chip" :class="r.pending === 0 ? 'on' : 'off'">
            {{
              r.pending === 0
                ? $t('settings.language.coverage.complete')
                : $t('settings.language.coverage.pending', { n: r.pending })
            }}
          </span>
        </div>
        <div class="hint">{{ $t('settings.language.coverage.contributeHint') }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.language.formats.title') }}</span>
        <span class="data text-small text-dim ml-10">{{ $t('settings.language.formats.sub') }}</span>
        <div class="spacer" />
        <button class="btn gh sm" @click="fm.reset()">
          <Icon name="refresh" :size="13" />
          {{ $t('settings.language.formats.reset') }}
        </button>
      </div>
      <div class="p-15 fgrid">
        <div class="flex flex-col gap-15">
          <div class="field">
            <label>{{ $t('settings.language.formats.region') }}</label>
            <SelectRoot v-model="fm.region">
              <SelectTrigger class="btn gh rk-select-trigger">
                <SelectValue />
                <Icon name="chevron-down" :size="14" class="text-dim" />
              </SelectTrigger>
              <SelectPortal>
                <SelectContent class="rk-select-content" position="popper" :side-offset="4">
                  <SelectViewport>
                    <SelectItem v-for="r in REGIONS" :key="r" :value="r" class="rk-select-item">
                      <SelectItemText>
                        {{ $t(`settings.language.formats.regions.${regionKey(r)}`, { tag: systemTag }) }}
                      </SelectItemText>
                    </SelectItem>
                  </SelectViewport>
                </SelectContent>
              </SelectPortal>
            </SelectRoot>
            <div class="hint">{{ $t('settings.language.formats.regionHint') }}</div>
          </div>

          <div class="field">
            <label>{{ $t('settings.language.formats.date') }}</label>
            <div class="seg">
              <button class="btn sm" :class="{ on: fm.dateStyle === 'iso' }" @click="fm.dateStyle = 'iso'">
                {{ $t('settings.language.formats.dateIso') }}
              </button>
              <button
                class="btn sm"
                :class="{ on: fm.dateStyle === 'locale' }"
                @click="fm.dateStyle = 'locale'"
              >
                {{ $t('settings.language.formats.dateLocale') }}
              </button>
            </div>
          </div>

          <div class="field">
            <label>{{ $t('settings.language.formats.time') }}</label>
            <div class="seg">
              <button class="btn sm" :class="{ on: !fm.hour12 }" @click="fm.hour12 = false">
                {{ $t('settings.language.formats.time24') }}
              </button>
              <button class="btn sm" :class="{ on: fm.hour12 }" @click="fm.hour12 = true">
                {{ $t('settings.language.formats.time12') }}
              </button>
            </div>
          </div>

          <div class="field">
            <label>{{ $t('settings.language.formats.size') }}</label>
            <div class="seg">
              <button
                class="btn sm"
                :class="{ on: fm.sizeUnit === 'binary' }"
                @click="fm.sizeUnit = 'binary'"
              >
                {{ $t('settings.language.formats.sizeBinary') }}
              </button>
              <button
                class="btn sm"
                :class="{ on: fm.sizeUnit === 'decimal' }"
                @click="fm.sizeUnit = 'decimal'"
              >
                {{ $t('settings.language.formats.sizeDecimal') }}
              </button>
            </div>
          </div>
        </div>

        <div class="preview">
          <div class="kv mb-10">{{ $t('settings.language.formats.preview') }}</div>
          <div>
            <label>{{ $t('settings.language.formats.previewNumber') }}</label>
            <span class="data">{{ preview.number }}</span>
          </div>
          <div>
            <label>{{ $t('settings.language.formats.previewDate') }}</label>
            <span class="data">{{ preview.date }}</span>
          </div>
          <div>
            <label>{{ $t('settings.language.formats.previewDateTime') }}</label>
            <span class="data">{{ preview.dateTime }}</span>
          </div>
          <div>
            <label>{{ $t('settings.language.formats.previewSize') }}</label>
            <span class="data">{{ preview.size }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.langs {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lang {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  text-align: left;
  border: 1px solid var(--line-soft);
  background: var(--bg);
  color: var(--tx);
  cursor: pointer;
  transition:
    border-color 0.12s,
    box-shadow 0.12s;
}
.lang:hover:not(:disabled) {
  border-color: var(--mut);
}
.lang.on {
  border-color: var(--ember);
  box-shadow: var(--glow);
}
.lang.soon {
  cursor: default;
  color: var(--dim);
}
.lang .native {
  font-size: 14px;
  font-weight: 600;
  min-width: 160px;
}
.lang .check {
  color: var(--ember);
  font-weight: 700;
}
.lang .spacer {
  flex: 1;
}
.cov {
  display: grid;
  grid-template-columns: 150px 130px 1fr 44px 110px auto;
  align-items: center;
  gap: 12px;
}
.cov .native {
  font-size: 13px;
  font-weight: 600;
}
.cov .pct {
  text-align: right;
  color: var(--tx);
}
.cov .keys {
  text-align: right;
}
.cov .chip {
  display: inline-flex;
  justify-self: end;
}
.fgrid {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 20px;
}
.seg {
  display: flex;
  gap: 6px;
}
.preview {
  border: 1px solid var(--line-soft);
  background: var(--bg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-self: start;
}
.preview > div:not(.kv) {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.preview label {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--dim);
}
</style>
