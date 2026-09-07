<script setup lang="ts">
import { LOCALES, setLocale } from '@/i18n';
/**
 * Settings. Theme lives in the webview only (localStorage) — it is the one
 * piece of state the daemon has no business knowing. Storage / network /
 * duplicates come from /api/config (secrets already redacted server-side).
 */

const { t, locale } = useI18n();
const ep = useEndpoint();
const theme = useTheme();
const src = useSources();

type Tab = 'accounts' | 'updates' | 'theme' | 'storage' | 'network' | 'duplicates' | 'about';

const tab = ref<Tab>('accounts');

const tabs: { id: Tab; label: string }[] = [
  { id: 'accounts', label: 'settings.tabs.accounts' },
  { id: 'updates', label: 'settings.tabs.updates' },
  { id: 'theme', label: 'settings.tabs.theme' },
  { id: 'storage', label: 'settings.tabs.storage' },
  { id: 'network', label: 'settings.tabs.network' },
  { id: 'duplicates', label: 'settings.tabs.duplicates' },
  { id: 'about', label: 'settings.tabs.about' },
];

/** Mirrors dawnmaker GET/PUT /api/config. Secrets arrive as booleans. */
interface Config {
  library_root: string;
  pixiv_rate: number;
  dupe_threshold: number;
  resolver: 'system' | 'doh';
  proxy_url: string | null;
  twitter_timeline_limit: number;
  pixiv_session: boolean;
  twitter_cookies: boolean;
}

const cfg = ref<Config | null>(null);

const draft = reactive({
  proxy_url: '',
  resolver: 'system' as Config['resolver'],
  dupe_threshold: 6,
  pixiv_rate: 1,
});

const status = ref('');

onMounted(async () => {
  try {
    cfg.value = await api.get<Config>('/api/config');
    draft.proxy_url = cfg.value.proxy_url ?? '';
    draft.resolver = cfg.value.resolver;
    draft.dupe_threshold = cfg.value.dupe_threshold;
    draft.pixiv_rate = cfg.value.pixiv_rate;
  } catch (e) {
    status.value = e instanceof Error ? e.message : String(e);
  }
});

async function saveNetwork() {
  status.value = t('settings.status.saving');
  try {
    cfg.value = await api.put<Config>('/api/config', {
      proxy_url: draft.proxy_url || null,
      resolver: draft.resolver,
      pixiv_rate: draft.pixiv_rate,
    });

    status.value = t('settings.status.savedNextJob');
  } catch (e) {
    status.value = e instanceof Error ? e.message : String(e);
  }
}

async function saveDedupe() {
  status.value = t('settings.status.saving');
  try {
    cfg.value = await api.put<Config>('/api/config', { dupe_threshold: draft.dupe_threshold });
    status.value = t('settings.status.saved');
  } catch (e) {
    status.value = e instanceof Error ? e.message : String(e);
  }
}

// ---- theme bindings (Reka sliders take number[]) ----
const opacity = computed({ get: () => [theme.plateOpacity], set: (v) => (theme.plateOpacity = v[0] ?? 1) });
const blur = computed({ get: () => [theme.plateBlur], set: (v) => (theme.plateBlur = v[0] ?? 0) });
const grid = computed({ get: () => [theme.gridAlpha], set: (v) => (theme.gridAlpha = v[0] ?? 0.05) });

const cutCorners = computed({
  get: () => theme.corners === 'cut',
  set: (v) => (theme.corners = v ? 'cut' : 'square'),
});

watch(
  () => [theme.bg, theme.plateOpacity, theme.plateBlur, theme.gridAlpha, theme.scanlines, theme.corners],
  () => theme.apply(),
  { deep: true },
);

const APP_VERSION = __APP_VERSION__; // vite.config `define`, from package.json
const BUILD = __GIT_SHA__;

const link = (u: string) =>
  import('@tauri-apps/plugin-opener').then((m) => m.openUrl(u)).catch(() => window.open(u));
</script>

<template>
  <div class="top">
    <div>
      <div class="h1">{{ $t('settings.title') }}</div>
      <div class="sub">{{ $t('settings.subtitle') }}</div>
    </div>
    <div class="spacer" />
    <span v-if="status" class="kv">{{ status }}</span>
  </div>

  <div class="body flex gap-20">
    <nav class="nav subnav w-200 shrink-0 flex flex-col gap-3">
      <button
        v-for="tb in tabs"
        :key="tb.id"
        :class="{ 'router-link-active': tab === tb.id }"
        @click="tab = tb.id"
      >
        {{ $t(tb.label) }}
      </button>
    </nav>

    <!-- ACCOUNTS -->
    <div v-if="tab === 'accounts'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.accounts.title') }}</span>
        <div class="spacer" />
        <span class="data text-small text-dim">{{ $t('settings.accounts.local') }}</span>
      </div>
      <div class="p-15 flex flex-col gap-10">
        <div class="hint mb-5">{{ $t('settings.accounts.intro') }}</div>
        <SourceCard source="pixiv" />
        <SourceCard source="twitter" />
        <SourceCard source="other" />
        <div v-if="src.dismissed" class="hint mt-5">{{ $t('settings.accounts.skipped') }}</div>
      </div>
    </div>

    <!-- UPDATES -->
    <UpdatesPanel v-else-if="tab === 'updates'" />

    <!-- THEME -->
    <div v-else-if="tab === 'theme'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.theme.title') }}</span>
        <div class="spacer" />
        <button class="btn gh sm" @click="theme.reset()">{{ $t('settings.theme.reset') }}</button>
      </div>
      <div class="p-15 flex flex-col gap-20">
        <div class="field">
          <label>{{ $t('settings.language.label') }}</label>
          <div class="flex items-center gap-10 flex-wrap">
            <button
              v-for="l in LOCALES"
              :key="l.code"
              class="btn sm"
              :class="{ on: locale === l.code }"
              :disabled="!l.ready"
              :title="l.ready ? l.label : $t('settings.language.soon', { name: l.label })"
              @click="setLocale(l.code)"
            >
              {{ l.label }}
              <span v-if="!l.ready" class="text-dim">·</span>
            </button>
          </div>
          <div class="hint">{{ $t('settings.language.hint') }}</div>
        </div>

        <div class="field">
          <label>{{ $t('settings.theme.background') }}</label>
          <div class="flex items-center gap-10">
            <input v-model="theme.bg" type="color" class="w-40 h-30 p-0 cursor-pointer" />
            <span class="data text-small text-mut">{{ theme.bg }}</span>
            <div class="spacer" />
            <button
              v-for="p in theme.presets"
              :key="p.name"
              class="w-20 h-20 border border-line"
              :style="{ background: p.bg }"
              :title="$t(`settings.theme.presets.${p.name}`)"
              @click="theme.bg = p.bg"
            />
          </div>
          <div class="hint">{{ $t('settings.theme.backgroundHint') }}</div>
        </div>

        <div class="field">
          <label>
            {{ $t('settings.theme.plateOpacity') }}
            <span class="data text-tx ml-5">
              {{ $t('settings.theme.percent', { n: Math.round(theme.plateOpacity * 100) }) }}
            </span>
          </label>
          <SliderRoot v-model="opacity" :min="0.3" :max="1" :step="0.01" class="rk-slider">
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.plateOpacityAria')" />
          </SliderRoot>
        </div>

        <div class="field">
          <label>
            {{ $t('settings.theme.plateBlur') }}
            <span class="data text-tx ml-5">{{ $t('settings.theme.px', { n: theme.plateBlur }) }}</span>
          </label>
          <SliderRoot v-model="blur" :min="0" :max="24" :step="1" class="rk-slider">
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.plateBlurAria')" />
          </SliderRoot>
          <div class="hint">{{ $t('settings.theme.plateBlurHint') }}</div>
        </div>

        <div class="field">
          <label>
            {{ $t('settings.theme.gridSubstrate') }}
            <span class="data text-tx ml-5">
              {{ $t('settings.theme.percent', { n: Math.round(theme.gridAlpha * 100) }) }}
            </span>
          </label>
          <SliderRoot v-model="grid" :min="0" :max="0.15" :step="0.005" class="rk-slider">
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.theme.gridAria')" />
          </SliderRoot>
        </div>

        <div class="flex items-center gap-10">
          <SwitchRoot id="scan" v-model="theme.scanlines" class="rk-switch">
            <SwitchThumb class="rk-switch-thumb" />
          </SwitchRoot>
          <label for="scan" class="text-small">{{ $t('settings.theme.scanlines') }}</label>
        </div>
        <div class="flex items-center gap-10">
          <SwitchRoot id="corners" v-model="cutCorners" class="rk-switch">
            <SwitchThumb class="rk-switch-thumb" />
          </SwitchRoot>
          <label for="corners" class="text-small">
            {{ $t('settings.theme.cutCorners') }}
            <span class="hint ml-5">{{ $t('settings.theme.cutCornersHint') }}</span>
          </label>
        </div>
      </div>
    </div>

    <!-- STORAGE -->
    <div v-else-if="tab === 'storage'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.storage.title') }}</span>
      </div>
      <table v-if="cfg">
        <tbody>
          <tr>
            <td class="kv">{{ $t('settings.storage.library') }}</td>
            <td class="data text-small">{{ cfg.library_root }}</td>
          </tr>
          <tr>
            <td class="kv">{{ $t('settings.storage.database') }}</td>
            <td class="data text-small">{{ ep.health?.db_path }}</td>
          </tr>
          <tr>
            <td class="kv">{{ $t('settings.storage.schema') }}</td>
            <td class="data text-small">
              {{ $t('settings.storage.schemaValue', { n: ep.health?.schema_version }) }}
            </td>
          </tr>
          <tr>
            <td class="kv">{{ $t('settings.storage.layout') }}</td>
            <td class="data text-small">{{ $t('settings.storage.layoutValue') }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">{{ status || $t('settings.status.loading') }}</div>
      <div class="p-15 hint">{{ $t('settings.storage.hint') }}</div>
    </div>

    <!-- NETWORK -->
    <div v-else-if="tab === 'network'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.network.title') }}</span>
        <div class="spacer" />
        <button class="btn pri sm" @click="saveNetwork">{{ $t('settings.network.save') }}</button>
      </div>
      <div v-if="cfg" class="p-15 flex flex-col gap-15">
        <div class="field">
          <label>{{ $t('settings.network.resolver') }}</label>
          <SelectRoot v-model="draft.resolver">
            <SelectTrigger class="btn gh rk-select-trigger">
              <SelectValue />
              <span class="text-dim">▾</span>
            </SelectTrigger>
            <SelectPortal>
              <SelectContent class="rk-select-content" position="popper" :side-offset="4">
                <SelectViewport>
                  <SelectItem value="system" class="rk-select-item">
                    <SelectItemText>{{ $t('settings.network.resolverSystem') }}</SelectItemText>
                  </SelectItem>
                  <SelectItem value="doh" class="rk-select-item">
                    <SelectItemText>{{ $t('settings.network.resolverDoh') }}</SelectItemText>
                  </SelectItem>
                </SelectViewport>
              </SelectContent>
            </SelectPortal>
          </SelectRoot>
          <div class="hint">{{ $t('settings.network.resolverHint') }}</div>
        </div>
        <div class="field">
          <label>{{ $t('settings.network.proxy') }}</label>
          <input
            v-model="draft.proxy_url"
            :placeholder="$t('settings.network.proxyPlaceholder')"
            class="data text-small"
          />
          <div class="hint">{{ $t('settings.network.proxyHint') }}</div>
        </div>
        <div class="field">
          <label>
            {{ $t('settings.network.pixivRate') }}
            <span class="data text-tx ml-5">
              {{ $t('settings.network.rateValue', { n: draft.pixiv_rate.toFixed(1) }) }}
            </span>
          </label>
          <SliderRoot
            :model-value="[draft.pixiv_rate]"
            :min="0.2"
            :max="2"
            :step="0.1"
            class="rk-slider"
            @update:model-value="(v) => (draft.pixiv_rate = v?.[0] ?? 1)"
          >
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.network.pixivRateAria')" />
          </SliderRoot>
          <div class="hint">{{ $t('settings.network.rateHint') }}</div>
        </div>
      </div>
      <div v-else class="empty">{{ status || $t('settings.status.loading') }}</div>
    </div>

    <!-- DUPLICATES -->
    <div v-else-if="tab === 'duplicates'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.duplicates.title') }}</span>
        <div class="spacer" />
        <button class="btn pri sm" @click="saveDedupe">{{ $t('settings.duplicates.save') }}</button>
      </div>
      <div class="p-15 flex flex-col gap-15">
        <div class="field">
          <label>
            {{ $t('settings.duplicates.distance') }}
            <span class="data text-tx ml-5">
              {{ $t('settings.duplicates.distanceValue', { n: draft.dupe_threshold }) }}
            </span>
          </label>
          <SliderRoot
            :model-value="[draft.dupe_threshold]"
            :min="0"
            :max="16"
            :step="1"
            class="rk-slider"
            @update:model-value="(v) => (draft.dupe_threshold = v?.[0] ?? 6)"
          >
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.duplicates.distanceAria')" />
          </SliderRoot>
          <div class="hint">{{ $t('settings.duplicates.hint') }}</div>
        </div>
      </div>
    </div>

    <!-- ABOUT -->
    <div v-else class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.about.title') }}</span>
      </div>
      <div class="p-15 flex flex-col gap-10">
        <div class="text-medium font-semibold">{{ $t('settings.about.name') }}</div>
        <div class="data text-small text-mut">
          {{
            $t('settings.about.version', { version: APP_VERSION, build: BUILD, crawler: ep.health?.version })
          }}
        </div>
        <div class="hint">{{ $t('settings.about.blurb') }}</div>
        <div class="flex gap-10 mt-10">
          <button class="btn gh sm" @click="link('https://www.pixiv.net/')">
            {{ $t('settings.about.pixiv') }}
          </button>
          <button class="btn gh sm" @click="link('https://github.com/')">
            {{ $t('settings.about.repository') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
