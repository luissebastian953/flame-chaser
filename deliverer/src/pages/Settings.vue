<script setup lang="ts">
import type { CleanupRule } from '@/lib/types';

/**
 * Settings. Theme lives in the webview only (localStorage) - it is the one
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
  | 'notifications'
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
  { id: 'notifications', label: 'settings.tabs.notifications', icon: 'bell' },
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
  cleanup_rule: CleanupRule | null;
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
  // Smart cleanup at crawl time (coreflame/trash.py crawl_verdict)
  rule_on: false,
  rule_score: 0.42 as number | null,
  rule_other: true,
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
    const rule = cfg.value.cleanup_rule;
    draft.rule_on = !!rule;
    draft.rule_score = rule ? rule.min_score : 0.42;
    draft.rule_other = rule ? rule.other_character : true;
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
    cfg.value = await api.put<Config>('/api/config', {
      dupe_threshold: draft.dupe_threshold,
      cleanup_rule: { active: draft.rule_on, min_score: draft.rule_score, other_character: draft.rule_other },
    });

    status.value = t('settings.status.saved');
  } catch (e) {
    status.value = e instanceof Error ? e.message : String(e);
  }
}

// ---- theme: the panel edits a draft; Apply (here, in the header) promotes it
function applyTheme() {
  theme.commit();
  status.value = t('settings.theme.applied');
}

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
    <template v-if="tab === 'theme'">
      <button class="btn gh" @click="theme.reset()">
        <Icon name="refresh" :size="13" />
        {{ $t('settings.theme.resetDefault') }}
      </button>
      <button class="btn pri" :disabled="!theme.dirty" @click="applyTheme">
        <Icon name="check" :size="13" />
        {{ $t('settings.theme.apply') }}
      </button>
    </template>
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

    <!-- NOTIFICATIONS: what Curio shows while it crawls in the background -->
    <NotificationsPanel v-else-if="tab === 'notifications'" />

    <!-- UPDATES -->
    <UpdatesPanel v-else-if="tab === 'updates'" />

    <!-- THEME -->
    <ThemePanel v-else-if="tab === 'theme'" />

    <!-- STORAGE: the library, the db and the disk; then the archive as one file -->
    <div v-else-if="tab === 'storage'" class="flex-1 flex flex-col gap-20 min-w-0">
      <StoragePanel />
      <BackupPanel @updates="tab = 'updates'" />
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
            @update:gender="(g) => defaults.set({ gender: g })"
            @update:mode="(m) => defaults.set({ gender_mode: m })"
          />
        </div>
        <div class="field">
          <div class="flex items-center gap-10">
            <SwitchRoot
              id="kind-filter-default"
              :model-value="defaults.kind_filter"
              class="rk-switch"
              @update:model-value="(v) => defaults.set({ kind_filter: v })"
            >
              <SwitchThumb class="rk-switch-thumb" />
            </SwitchRoot>
            <label for="kind-filter-default" class="text-small">{{ $t('settings.characters.kinds') }}</label>
          </div>
          <div class="hint">{{ $t('settings.characters.kindsHint') }}</div>
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
        <div class="field">
          <label class="flex items-center gap-10">
            <SwitchRoot v-model="draft.rule_on" class="rk-switch">
              <SwitchThumb class="rk-switch-thumb" />
            </SwitchRoot>
            {{ $t('settings.duplicates.rule') }}
            <span v-if="cfg?.cleanup_rule" class="chip on">
              {{ $t('crawl.cards.recognition.ruleActive') }}
            </span>
          </label>
          <div class="flex flex-col gap-15 pl-20 mt-10 mb-5" :class="{ 'opacity-50': !draft.rule_on }">
            <label class="flex items-center gap-10">
              <CheckboxRoot
                :model-value="draft.rule_score !== null"
                :disabled="!draft.rule_on"
                class="rk-checkbox"
                @update:model-value="(v) => (draft.rule_score = v === true ? 0.42 : null)"
              />
              {{ $t('settings.duplicates.ruleScore') }}
              <span class="data text-tx">
                {{
                  draft.rule_score === null
                    ? $t('settings.duplicates.ruleScoreOff')
                    : draft.rule_score.toFixed(2)
                }}
              </span>
            </label>
            <SliderRoot
              :model-value="[draft.rule_score ?? 0.42]"
              :min="0"
              :max="1"
              :step="0.01"
              :disabled="!draft.rule_on || draft.rule_score === null"
              class="rk-slider"
              @update:model-value="(v) => (draft.rule_score = v?.[0] ?? 0.42)"
            >
              <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
              <SliderThumb class="rk-slider-thumb" :aria-label="$t('settings.duplicates.ruleScoreAria')" />
            </SliderRoot>
            <label class="flex items-center gap-10">
              <CheckboxRoot
                :model-value="draft.rule_other"
                :disabled="!draft.rule_on"
                class="rk-checkbox"
                @update:model-value="(v) => (draft.rule_other = v === true)"
              />
              {{ $t('settings.duplicates.ruleOther') }}
            </label>
          </div>
          <div class="hint">{{ $t('settings.duplicates.ruleHint') }}</div>
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
