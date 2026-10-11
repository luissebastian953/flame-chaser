<script setup lang="ts">
/**
 * Settings. Theme lives in the webview only (localStorage) — it is the one
 * piece of state the daemon has no business knowing. Storage / network /
 * duplicates come from /api/config (secrets already redacted server-side).
 */

const { t } = useI18n();
const ep = useEndpoint();
const theme = useTheme();
const defaults = useCharacterDefaults();
const src = useSources();

type Tab =
  | 'accounts'
  | 'language'
  | 'updates'
  | 'theme'
  | 'storage'
  | 'network'
  | 'duplicates'
  | 'characters'
  | 'about';

const tab = ref<Tab>('accounts');

const tabs: { id: Tab; label: string; icon: string }[] = [
  { id: 'accounts', label: 'settings.tabs.accounts', icon: 'user' },
  { id: 'language', label: 'settings.tabs.language', icon: 'language' },
  { id: 'updates', label: 'settings.tabs.updates', icon: 'update' },
  { id: 'theme', label: 'settings.tabs.theme', icon: 'palette' },
  { id: 'storage', label: 'settings.tabs.storage', icon: 'drive' },
  { id: 'network', label: 'settings.tabs.network', icon: 'signal' },
  { id: 'duplicates', label: 'settings.tabs.duplicates', icon: 'layers' },
  { id: 'characters', label: 'settings.tabs.characters', icon: 'users' },
  { id: 'about', label: 'settings.tabs.about', icon: 'info' },
];

/** Mirrors dawnmaker GET/PUT /api/config. Secrets arrive as booleans. */
interface Config {
  library_root: string;
  pixiv_rate: number;
  dupe_threshold: number;
  resolver: 'system' | 'doh';
  proxy_url: string | null;
  twitter_timeline_limit: number;
  twitter_search_limit: number;
  identify_characters: boolean;
  pixiv_session: boolean;
  twitter_cookies: boolean;
}

const cfg = ref<Config | null>(null);

const draft = reactive({
  proxy_url: '',
  resolver: 'system' as Config['resolver'],
  dupe_threshold: 6,
  pixiv_rate: 1,
  twitter_search_limit: 50,
});

const status = ref('');

onMounted(async () => {
  try {
    cfg.value = await api.get<Config>('/api/config');
    draft.proxy_url = cfg.value.proxy_url ?? '';
    draft.resolver = cfg.value.resolver;
    draft.dupe_threshold = cfg.value.dupe_threshold;
    draft.pixiv_rate = cfg.value.pixiv_rate;
    draft.twitter_search_limit = cfg.value.twitter_search_limit ?? 50;
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
      twitter_search_limit: draft.twitter_search_limit,
    });

    status.value = t('settings.status.savedNextJob');
  } catch (e) {
    status.value = e instanceof Error ? e.message : String(e);
  }
}

/** Settings › Characters: name the character in every image (coreflame/identify.py). */
const identify = computed({
  get: () => cfg.value?.identify_characters ?? true,
  set: (v: boolean) => void saveIdentify(v),
});

async function saveIdentify(on: boolean) {
  status.value = t('settings.status.saving');
  try {
    cfg.value = await api.put<Config>('/api/config', { identify_characters: on });
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

  <!-- items-start: a tab is as tall as its content and .body scrolls; stretched to the
       window height, a .panel (overflow: hidden, for the cut corners) clipped it -->
  <div class="body flex items-start gap-20">
    <nav class="nav subnav w-200 shrink-0 flex flex-col gap-3 sticky top-0">
      <button
        v-for="tb in tabs"
        :key="tb.id"
        :class="{ 'router-link-active': tab === tb.id }"
        @click="tab = tb.id"
      >
        <Icon :name="tb.icon" class="ic" />
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

    <!-- LANGUAGE -->
    <LanguagePanel v-else-if="tab === 'language'" />

    <!-- UPDATES -->
    <UpdatesPanel v-else-if="tab === 'updates'" />

    <!-- THEME -->
    <div v-else-if="tab === 'theme'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.theme.title') }}</span>
        <div class="spacer" />
        <button class="btn gh sm" @click="theme.reset()">
          <Icon name="refresh" :size="13" />
          {{ $t('settings.theme.reset') }}
        </button>
      </div>
      <div class="p-15 flex flex-col gap-20">
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
            <td class="kv">
              <Icon name="folder" :size="13" class="mr-5" />
              {{ $t('settings.storage.library') }}
            </td>
            <td class="data text-small">{{ cfg.library_root }}</td>
          </tr>
          <tr>
            <td class="kv">
              <Icon name="database" :size="13" class="mr-5" />
              {{ $t('settings.storage.database') }}
            </td>
            <td class="data text-small">{{ ep.health?.db_path }}</td>
          </tr>
          <tr>
            <td class="kv">
              <Icon name="list" :size="13" class="mr-5" />
              {{ $t('settings.storage.schema') }}
            </td>
            <td class="data text-small">
              {{ $t('settings.storage.schemaValue', { n: ep.health?.schema_version }) }}
            </td>
          </tr>
          <tr>
            <td class="kv">
              <Icon name="archive" :size="13" class="mr-5" />
              {{ $t('settings.storage.layout') }}
            </td>
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
        <button class="btn pri sm" @click="saveNetwork">
          <Icon name="save" :size="13" />
          {{ $t('settings.network.save') }}
        </button>
      </div>
      <div v-if="cfg" class="p-15 flex flex-col gap-15">
        <div class="field">
          <label>{{ $t('settings.network.resolver') }}</label>
          <SelectRoot v-model="draft.resolver">
            <SelectTrigger class="btn gh rk-select-trigger">
              <SelectValue />
              <Icon name="chevron-down" :size="14" class="text-dim" />
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
        <div class="field">
          <label>
            {{ $t('settings.network.xSearch') }}
            <span class="data text-tx ml-5">
              {{
                draft.twitter_search_limit
                  ? $t('settings.network.xSearchValue', { n: draft.twitter_search_limit })
                  : $t('settings.network.xSearchOff')
              }}
            </span>
          </label>
          <SliderRoot
            :model-value="[draft.twitter_search_limit]"
            :min="0"
            :max="200"
            :step="10"
            class="rk-slider"
            @update:model-value="(v) => (draft.twitter_search_limit = v?.[0] ?? 50)"
          >
            <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
            <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.network.xSearch')" />
          </SliderRoot>
          <div class="hint">{{ $t('settings.network.xSearchHint') }}</div>
        </div>
      </div>
      <div v-else class="empty">{{ status || $t('settings.status.loading') }}</div>
    </div>

    <!-- DUPLICATES -->
    <!-- CHARACTERS: what a new character's form starts with -->
    <div v-else-if="tab === 'characters'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.characters.title') }}</span>
      </div>
      <div class="p-15 flex flex-col gap-15">
        <div class="hint">{{ $t('settings.characters.lead') }}</div>
        <div class="field">
          <label>{{ $t('character.gender.label') }}</label>
          <GenderFilter
            :gender="defaults.gender"
            :mode="defaults.gender_mode"
            @update:gender="(g) => defaults.set(g, defaults.gender_mode)"
            @update:mode="(m) => defaults.set(defaults.gender, m)"
          />
        </div>
        <div v-if="cfg" class="field">
          <div class="flex items-center gap-10">
            <SwitchRoot id="identify" v-model="identify" class="rk-switch">
              <SwitchThumb class="rk-switch-thumb" />
            </SwitchRoot>
            <label for="identify" class="text-small">{{ $t('settings.characters.identify') }}</label>
          </div>
          <div class="hint">{{ $t('settings.characters.identifyHint') }}</div>
          <div v-if="status" class="hint">{{ status }}</div>
        </div>
      </div>
    </div>

    <div v-else-if="tab === 'duplicates'" class="panel flex-1">
      <div class="phead">
        <span class="ptitle">{{ $t('settings.duplicates.title') }}</span>
        <div class="spacer" />
        <button class="btn pri sm" @click="saveDedupe">
          <Icon name="save" :size="13" />
          {{ $t('settings.duplicates.save') }}
        </button>
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
            <Icon name="external" :size="13" />
            {{ $t('settings.about.pixiv') }}
          </button>
          <button class="btn gh sm" @click="link('https://github.com/')">
            <Icon name="external" :size="13" />
            {{ $t('settings.about.repository') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
