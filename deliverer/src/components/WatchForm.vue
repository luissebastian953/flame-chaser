<script setup lang="ts">
/**
 * Add / edit character. Everything on the right and in the footer comes from
 * POST /api/pixiv/probe -- one search page per tag, debounced here, cached in
 * the daemon. The slug is derived from the name and frozen after the first
 * save: folder names and post_watches rows key off it.
 */
import type { CharacterNames, NameSuggestion, ProbeResult, Source, Watch } from '@/lib/types';

const props = defineProps<{ watch: Watch; isNew: boolean }>();
const emit = defineEmits<{ save: [w: Watch, run: boolean]; close: [] }>();
const src = useSources();
const router = useRouter();
const { t } = useI18n();

/** Desktop: the login window. Browser mode: hand off to Settings › Accounts. */
function connect(source: 'pixiv' | 'twitter') {
  if (src.inTauri) void src.connectViaWindow(source);
  else {
    emit('close');
    void router.push('/settings');
  }
}

const w = reactive<Watch>({
  ...props.watch,
  pixiv_tags: [...props.watch.pixiv_tags],
  match_terms: [...props.watch.match_terms],
  sources: [...(props.watch.sources ?? ['pixiv', 'twitter'])],
  target: props.watch.target ?? 100,
  kind_filter: props.watch.kind_filter ?? true,
  gender: props.watch.gender ?? 'any',
  gender_mode: props.watch.gender_mode ?? 'full',
});

// ---- sources: which of pixiv / X this character is crawled from ------------
const uses = (s: Source) => w.sources.includes(s);

function setSource(s: Source, on: boolean | 'indeterminate') {
  const next = w.sources.filter((x) => x !== s);
  if (on === true) next.push(s);
  // keep the canonical order so the API and the table agree
  w.sources = (['pixiv', 'twitter'] as Source[]).filter((x) => next.includes(x));
}

const newTag = ref('');
const newTerm = ref('');
const err = ref('');
const probe = ref<ProbeResult | null>(null);
const probing = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;

const slugify = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

const slugPreview = computed(() => w.slug || slugify(w.label) || '');

// ---- tags ------------------------------------------------------------------
const FULLWIDTH = /[（）]/;

function addTag() {
  const t = newTag.value.trim();
  if (t && !w.pixiv_tags.includes(t)) w.pixiv_tags.push(t);
  newTag.value = '';
}

function addTerm() {
  const t = newTerm.value.trim();
  if (t && !w.match_terms.includes(t)) w.match_terms.push(t);
  newTerm.value = '';
}

function addSuggested(raw: string) {
  if (!w.pixiv_tags.includes(raw)) w.pixiv_tags.push(raw);
}

const tagStatus = (t: string) => probe.value?.tags.find((p) => p.tag === t) ?? null;

// ---- probe (debounced) -----------------------------------------------------
async function runProbe() {
  if (!uses('pixiv') || (src.status && !src.pixivOk)) {
    probe.value = null;
    return;
  } // badge explains; no request spent
  const tags = w.pixiv_tags.filter((t) => !FULLWIDTH.test(t)).slice(0, 8);
  const fw = w.pixiv_tags.filter((t) => FULLWIDTH.test(t));
  if (!tags.length && !fw.length) {
    probe.value = null;
    return;
  }
  probing.value = true;
  try {
    const r = await api.post<ProbeResult>('/api/pixiv/probe', {
      tags: [...tags, ...fw],
      include_r18: w.include_r18,
    });

    probe.value = r;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    probing.value = false;
  }
}

watch(
  () => [w.pixiv_tags.join('\u0000'), w.include_r18, uses('pixiv')],
  () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(runProbe, 350);
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
  if (namesTimer) clearTimeout(namesTimer);
});

const suggestions = computed(() =>
  (probe.value?.suggestions ?? []).filter((s) => !w.pixiv_tags.includes(s.tag_raw)),
);

// ---- names from Danbooru + Wikidata (debounced; no pixiv session needed) -----
const names = ref<CharacterNames | null>(null);
const looking = ref(false);
const showAll = reactive({ name: false, form: false });
const GROUP_N = 6;
let namesTimer: ReturnType<typeof setTimeout> | null = null;

const norm = (x: string) => x.normalize('NFKC').toLowerCase().trim();
const have = computed(() => new Set([...w.pixiv_tags, ...w.match_terms].map(norm)));

/** the display name first: it is what Danbooru and Wikidata know best */
const nameQueries = computed(() =>
  [...new Set([w.label, ...w.pixiv_tags, ...w.match_terms].map((x) => x.trim()).filter(Boolean))].slice(0, 8),
);

async function lookUpNames() {
  const queries = nameQueries.value;
  if (!queries.length) {
    names.value = null;
    return;
  }
  looking.value = true;
  try {
    names.value = await api.post<CharacterNames>('/api/names', { queries });
  } catch {
    names.value = null; // the panel just shows no names; the form still works
  } finally {
    looking.value = false;
  }
}

watch(
  () => nameQueries.value.join('\u0000'),
  () => {
    if (namesTimer) clearTimeout(namesTimer);
    namesTimer = setTimeout(lookUpNames, 600);
  },
  { immediate: true },
);

const fresh = (kind: NameSuggestion['kind']) =>
  (names.value?.suggestions ?? []).filter((x) => x.kind === kind && !have.value.has(norm(x.text)));

const nameRows = computed(() => fresh('name'));
const formRows = computed(() => fresh('form'));

const visible = (rows: NameSuggestion[], kind: 'name' | 'form') =>
  showAll[kind] ? rows : rows.slice(0, GROUP_N);

const downSources = computed(() => Object.keys(names.value?.errors ?? {}));

function addAsTag(text: string) {
  if (!w.pixiv_tags.includes(text)) w.pixiv_tags.push(text);
}

function addAsTerm(text: string) {
  if (!w.match_terms.includes(text)) w.match_terms.push(text);
}

// ---- crawl target: posts per run, and what the next runs will do ------------
const PRESETS = [100, 300, 500, 1000];
const TARGET_MAX = 1000; // the daemon enforces the same range
const clampTarget = (n: number) => Math.min(TARGET_MAX, Math.max(1, Math.round(Number(n)) || 100));

/** posts this character already holds: run 1 continues after them */
const kept = computed(() => props.watch.post_count ?? 0);

/** pixiv reports how many artworks the tags hold (an upper bound: tags
 * overlap); X search reports no totals, so an X-only character has none */
const total = computed(() => (uses('pixiv') && probe.value?.estimate?.artworks) || null);
const left = computed(() => (total.value === null ? null : Math.max(0, total.value - kept.value - w.target)));
const pct = (n: number) => `${total.value ? Math.min(100, (n / total.value) * 100) : 0}%`;

function duration(seconds: number) {
  const m = Math.round(seconds / 60);

  return m < 1
    ? t('character.estimate.underMinute')
    : m < 90
      ? t('character.estimate.aboutMinutes', { m })
      : t('character.estimate.aboutHours', { h: (m / 60).toFixed(1) });
}

// this run's share of the probe's whole-backfill estimate
const runTime = computed(() => {
  const e = probe.value?.estimate;

  return e?.artworks ? duration(e.seconds * Math.min(1, w.target / e.artworks)) : null;
});

// ---- submit ----------------------------------------------------------------
function validate(): boolean {
  err.value = '';
  if (!w.label.trim()) {
    err.value = t('character.errors.name');
    return false;
  }
  if (!w.slug) w.slug = slugify(w.label);
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(w.slug)) {
    err.value = t('character.errors.slug');
    return false;
  }
  if (!w.sources.length) {
    err.value = t('character.errors.noSource');
    return false;
  }
  if (uses('pixiv')) {
    if (!w.pixiv_tags.length) {
      err.value = t('character.errors.noTags');
      return false;
    }
    if (w.pixiv_tags.every((t) => FULLWIDTH.test(t))) {
      err.value = t('character.errors.allFullwidth');
      return false;
    }
  } else if (uses('twitter') && !w.match_terms.length) {
    // pixiv-off: the slug fallback in the matcher is too loose to be the only filter
    err.value = t('character.errors.noTerms');
    return false;
  }
  return true;
}

function submit(run: boolean) {
  w.target = clampTarget(w.target);
  if (validate()) {
    emit(
      'save',
      { ...w, pixiv_tags: [...w.pixiv_tags], match_terms: [...w.match_terms], sources: [...w.sources] },
      run,
    );
  }
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <div class="modal panel square">
      <div class="phead head">
        <div>
          <div class="text-medium font-semibold">
            {{ isNew ? $t('character.title.add') : $t('character.title.edit', { name: w.label || w.slug }) }}
          </div>
          <div class="data text-small text-dim">{{ $t('character.title.tagline') }}</div>
        </div>
        <div class="spacer" />
        <button class="btn gh sm" :aria-label="$t('character.close')" @click="emit('close')">
          <Icon name="close" :size="14" />
        </button>
      </div>

      <div class="cols">
        <!-- ============================== main column -->
        <div class="main-col">
          <div class="grid2">
            <div class="field">
              <label>
                {{ $t('character.name.label') }}
                <span class="hint">{{ $t('character.name.hint') }}</span>
              </label>
              <input v-model="w.label" :placeholder="$t('character.name.placeholder')" autofocus />
            </div>
            <div class="field">
              <label>
                {{ $t('character.slug.label') }}
                <span class="hint">
                  {{ isNew ? $t('character.slug.hintNew') : $t('character.slug.hintFrozen') }}
                </span>
              </label>
              <input
                :value="slugPreview"
                class="data text-small"
                disabled
                :placeholder="isNew ? $t('character.slug.placeholder') : ''"
              />
            </div>
          </div>

          <div class="sec" :class="{ off: !uses('pixiv') }">
            <div class="sec-h">
              <span class="n">1</span>
              <b>{{ $t('character.tags.heading') }}</b>
              <AuthBadge
                v-if="uses('pixiv')"
                :state="src.pixivOk ? 'on' : src.status?.pixiv.verified === false ? 'expired' : 'off'"
                @connect="connect('pixiv')"
              />
              <span class="spacer" />
              <label class="src-toggle">
                <CheckboxRoot
                  id="src-pixiv"
                  :model-value="uses('pixiv')"
                  class="rk-checkbox"
                  @update:model-value="(v) => setSource('pixiv', v)"
                >
                  <CheckboxIndicator />
                </CheckboxRoot>
                <span class="text-small">{{ $t('character.sources.pixiv') }}</span>
              </label>
            </div>
            <div class="hint">
              {{ uses('pixiv') ? $t('character.tags.hint') : $t('character.sources.off') }}
            </div>
            <div v-if="uses('pixiv')" class="rows">
              <div
                v-for="(tag, i) in w.pixiv_tags"
                :key="tag"
                class="row"
                :class="{ bad: tagStatus(tag)?.warning || tagStatus(tag)?.error }"
              >
                <input :value="tag" class="jp" readonly />
                <span class="stat">
                  <template v-if="!tagStatus(tag)">
                    <span class="text-dim data text-small">
                      {{ probing ? $t('character.tags.checking') : '' }}
                    </span>
                  </template>
                  <template v-else-if="tagStatus(tag)!.ok">
                    <span class="ok">
                      <Icon name="check" :size="13" />
                      {{
                        $t(
                          'character.tags.artworks',
                          { n: tagStatus(tag)!.total.toLocaleString() },
                          tagStatus(tag)!.total,
                        )
                      }}
                    </span>
                  </template>
                  <template v-else-if="tagStatus(tag)!.error">
                    <span class="err">
                      <Icon name="warning" :size="13" />
                      {{ $t('character.tags.error', { error: tagStatus(tag)!.error }) }}
                    </span>
                  </template>
                  <template v-else>
                    <span class="err">
                      <Icon name="warning" :size="13" />
                      {{ $t('character.tags.warning', { warning: tagStatus(tag)!.warning }) }}
                    </span>
                  </template>
                </span>
                <button
                  class="btn gh sm"
                  :aria-label="$t('character.tags.remove')"
                  @click="w.pixiv_tags.splice(i, 1)"
                >
                  <Icon name="close" :size="13" />
                </button>
              </div>
              <input
                v-model="newTag"
                class="jp add"
                :placeholder="$t('character.tags.placeholder')"
                @keydown.enter.prevent="addTag"
                @blur="addTag"
              />
            </div>
          </div>

          <div class="sec" :class="{ off: !uses('twitter') }">
            <div class="sec-h">
              <span class="n">2</span>
              <b>{{ $t('character.terms.heading') }}</b>
              <AuthBadge
                v-if="uses('twitter')"
                :state="src.twitterOk ? 'on' : 'off'"
                @connect="connect('twitter')"
              />
              <span class="spacer" />
              <label class="src-toggle">
                <CheckboxRoot
                  id="src-twitter"
                  :model-value="uses('twitter')"
                  class="rk-checkbox"
                  @update:model-value="(v) => setSource('twitter', v)"
                >
                  <CheckboxIndicator />
                </CheckboxRoot>
                <span class="text-small">{{ $t('character.sources.x') }}</span>
              </label>
            </div>
            <div class="hint">
              {{ uses('twitter') ? $t('character.terms.hint') : $t('character.sources.off') }}
            </div>
            <div v-if="uses('twitter')" class="chips">
              <span v-for="(term, i) in w.match_terms" :key="term" class="chip mono">
                {{ term }}
                <button
                  class="x"
                  :aria-label="$t('character.terms.remove')"
                  @click="w.match_terms.splice(i, 1)"
                >
                  <Icon name="close" :size="11" />
                </button>
              </span>
              <input
                v-model="newTerm"
                class="term"
                :placeholder="$t('character.terms.placeholder')"
                @keydown.enter.prevent="addTerm"
                @blur="addTerm"
              />
            </div>
          </div>

          <div class="sec">
            <div class="sec-h">
              <span class="n">3</span>
              <b>{{ $t('character.crawl.heading') }}</b>
            </div>
            <div class="hint">{{ $t('character.crawl.hint') }}</div>
            <div class="target-grid">
              <div class="field">
                <label for="posts-per-run">{{ $t('character.crawl.perRun') }}</label>
                <div class="flex items-center gap-10 flex-wrap">
                  <input
                    id="posts-per-run"
                    v-model.number="w.target"
                    type="number"
                    min="1"
                    :max="TARGET_MAX"
                    class="data w-100 text-right"
                    @change="w.target = clampTarget(w.target)"
                  />
                  <span class="text-small text-dim">{{ $t('character.crawl.posts') }}</span>
                  <button
                    v-for="n in PRESETS"
                    :key="n"
                    type="button"
                    class="chip preset data"
                    :class="{ on: w.target === n }"
                    :aria-pressed="w.target === n"
                    @click="w.target = n"
                  >
                    {{ n }}
                  </button>
                </div>
              </div>
              <div class="field" :class="{ inert: !uses('pixiv') }">
                <label for="min-bookmarks">
                  {{ $t('character.bookmarks.label') }}
                  <span class="hint">{{ $t('character.bookmarks.hint') }}</span>
                  <InfoTip :label="$t('character.bookmarks.helpLabel')">
                    <p>{{ $t('character.bookmarks.help.what') }}</p>
                    <p>{{ $t('character.bookmarks.help.rule') }}</p>
                    <p>{{ $t('character.bookmarks.help.raise') }}</p>
                    <p>{{ $t('character.bookmarks.help.lower') }}</p>
                    <p>{{ $t('character.bookmarks.help.x') }}</p>
                  </InfoTip>
                </label>
                <input
                  id="min-bookmarks"
                  v-model.number="w.min_bookmarks"
                  type="number"
                  min="0"
                  class="data w-100 text-right"
                />
                <div class="hint">
                  {{ uses('pixiv') ? $t('character.bookmarks.note') : $t('character.bookmarks.pixivOff') }}
                </div>
              </div>
            </div>
            <div class="grid2 align-start">
              <div class="toggle">
                <SwitchRoot id="kind-filter" v-model="w.kind_filter" class="rk-switch">
                  <SwitchThumb class="rk-switch-thumb" />
                </SwitchRoot>
                <label for="kind-filter">
                  <span class="text-small">{{ $t('character.recognition.label') }}</span>
                  <span class="hint">
                    {{ w.kind_filter ? $t('character.recognition.on') : $t('character.recognition.off') }}
                  </span>
                </label>
              </div>
              <div class="toggle">
                <SwitchRoot id="r18" v-model="w.include_r18" class="rk-switch">
                  <SwitchThumb class="rk-switch-thumb" />
                </SwitchRoot>
                <label for="r18">
                  <span class="text-small">
                    {{ $t('character.r18.label') }}
                  </span>
                  <span class="hint">
                    {{ w.include_r18 ? $t('character.r18.on') : $t('character.r18.off') }}
                  </span>
                </label>
              </div>
            </div>
            <div class="field">
              <label>{{ $t('character.gender.label') }}</label>
              <GenderFilter v-model:gender="w.gender" v-model:mode="w.gender_mode" />
            </div>
          </div>

          <div v-if="probe?.preview.length" class="sec preview">
            <div class="sec-h">
              <Icon name="eye" :size="14" class="text-dim" />
              <b>{{ $t('character.preview.heading') }}</b>
              <span class="hint">{{ $t('character.preview.lead', { tag: w.pixiv_tags[0] }) }}</span>
            </div>
            <div class="strip">
              <div
                v-for="p in probe.preview"
                :key="p.illust_id"
                class="tile"
                :title="`${p.title} — ${p.artist_name}`"
              >
                <img v-if="p.thumb" :src="authedUrl(p.thumb)" loading="lazy" alt="" />
              </div>
            </div>
          </div>

          <div v-if="err" class="err">{{ err }}</div>
        </div>

        <!-- ============================== suggestions -->
        <aside class="side-col">
          <div class="ptitle">{{ $t('character.suggestions.heading') }}</div>
          <div class="hint">{{ $t('character.suggestions.lead') }}</div>
          <!-- a fixed-height box that scrolls, so the run cycle stays in view -->
          <div class="sug-scroll">
            <div v-if="downSources.length" class="hint err">
              <Icon name="warning" :size="12" />
              {{ $t('character.suggestions.sourceDown', { source: downSources.join(' + ') }) }}
            </div>

            <template v-for="group in ['name', 'form'] as const" :key="group">
              <div v-if="(group === 'name' ? nameRows : formRows).length" class="nm-group">
                <div class="nm-h">
                  {{
                    group === 'name' ? $t('character.suggestions.names') : $t('character.suggestions.forms')
                  }}
                </div>
                <div
                  v-for="s in visible(group === 'name' ? nameRows : formRows, group)"
                  :key="s.text"
                  class="nm-row"
                  :class="{ risky: s.risky }"
                >
                  <div class="nm-text">
                    <span class="jp">{{ s.text }}</span>
                    <span class="nm-meta data">
                      <span v-if="s.lang" class="lang">{{ $t(`character.suggestions.lang.${s.lang}`) }}</span>
                      <span v-if="s.posts">
                        {{ $t('character.suggestions.posts', { n: s.posts.toLocaleString() }, s.posts) }}
                      </span>
                      <span v-if="s.risky" class="warn">{{ $t('character.suggestions.risky') }}</span>
                    </span>
                  </div>
                  <div class="nm-add">
                    <button
                      v-if="uses('pixiv')"
                      type="button"
                      class="add"
                      :aria-label="$t('character.suggestions.addPixivLabel', { text: s.text })"
                      @click="addAsTag(s.text)"
                    >
                      <Icon name="plus" :size="11" />
                      {{ $t('character.suggestions.addPixiv') }}
                    </button>
                    <button
                      v-if="uses('twitter')"
                      type="button"
                      class="add"
                      :aria-label="$t('character.suggestions.addXLabel', { text: s.text })"
                      @click="addAsTerm(s.text)"
                    >
                      <Icon name="plus" :size="11" />
                      {{ $t('character.suggestions.addX') }}
                    </button>
                  </div>
                </div>
                <button
                  v-if="(group === 'name' ? nameRows : formRows).length > GROUP_N"
                  type="button"
                  class="more"
                  @click="showAll[group] = !showAll[group]"
                >
                  <Icon v-if="showAll[group]" name="chevron-up" :size="12" />
                  <Icon v-else name="chevron-down" :size="12" />
                  {{
                    showAll[group]
                      ? $t('character.suggestions.less')
                      : $t('character.suggestions.more', {
                          n: (group === 'name' ? nameRows : formRows).length - GROUP_N,
                        })
                  }}
                </button>
              </div>
            </template>

            <div v-if="suggestions.length" class="nm-group">
              <div class="nm-h">{{ $t('character.suggestions.pixiv') }}</div>
              <div class="sug">
                <div
                  v-for="s in suggestions"
                  :key="s.tag_norm"
                  class="sug-row"
                  :class="{ low: s.score < 0.3 }"
                >
                  <span class="jp">{{ s.tag_raw }}</span>
                  <span class="data text-small text-right">
                    <span :class="s.score >= 0.3 ? 'text-ember' : 'text-dim'">{{ s.score.toFixed(2) }}</span>
                    <br />
                    <span class="text-dim">{{ Math.round(s.share * 100) }}%</span>
                  </span>
                  <button v-if="s.score >= 0.3" class="add" @click="addSuggested(s.tag_raw)">
                    <Icon name="plus" :size="11" />
                    {{ $t('character.suggestions.add') }}
                  </button>
                  <span v-else class="text-dim">—</span>
                </div>
              </div>
            </div>

            <div v-if="!nameRows.length && !formRows.length && !suggestions.length" class="hint mt-15">
              {{
                looking
                  ? $t('character.suggestions.looking')
                  : probing
                    ? $t('character.suggestions.checking')
                    : !nameQueries.length
                      ? $t('character.suggestions.empty')
                      : names
                        ? $t('character.suggestions.nothing')
                        : $t('character.suggestions.none')
              }}
            </div>
            <div v-else-if="looking" class="hint">{{ $t('character.suggestions.looking') }}</div>
          </div>
          <div class="cycle">
            <div class="flex items-center">
              <span class="ptitle">{{ $t('character.cycle.heading') }}</span>
              <span class="spacer" />
              <span class="data text-small text-dim">
                {{ $t('character.cycle.perRun', { n: w.target }) }}
              </span>
            </div>
            <div v-if="total" class="cycle-bar">
              <span class="done" :style="{ width: pct(kept) }" />
              <span class="now" :style="{ width: pct(w.target) }" />
            </div>
            <div class="legend text-small">
              <span>
                <i class="dot now" />
                {{ $t('character.cycle.thisRun', { n: w.target }) }}
              </span>
              <span>
                <i class="dot" />
                {{
                  left === null
                    ? $t('character.cycle.leftUnknown')
                    : $t('character.cycle.left', { n: left.toLocaleString() })
                }}
              </span>
            </div>
            <div class="runs">
              <div class="run-row first">
                <span class="data">{{ $t('character.cycle.run', { n: 1 }) }}</span>
                <span>{{ $t('character.cycle.posts', { from: kept + 1, to: kept + w.target }) }}</span>
                <span class="text-dim">{{ $t('character.cycle.onSave') }}</span>
              </div>
              <div class="run-row">
                <span class="data">{{ $t('character.cycle.run', { n: 2 }) }}</span>
                <span>{{ $t('character.cycle.next', { n: w.target }) }}</span>
                <span class="text-dim">{{ $t('character.cycle.skipsOne', { n: 1 }) }}</span>
              </div>
              <div class="run-row">
                <span class="data">{{ $t('character.cycle.run', { n: 3 }) }}</span>
                <span>{{ $t('character.cycle.next', { n: w.target }) }}</span>
                <span class="text-dim">{{ $t('character.cycle.skipsRange', { from: 1, to: 2 }) }}</span>
              </div>
            </div>
            <div class="hint">{{ $t('character.cycle.note') }}</div>
          </div>
          <div class="spacer" />
          <div class="hint">{{ $t('character.suggestions.refresh') }}</div>
        </aside>
      </div>

      <div class="foot">
        <i18n-t v-if="total" keypath="character.run.line" tag="span" class="data text-small text-dim">
          <template #n>
            <b class="text-tx">{{ w.target }}</b>
          </template>
          <template #total>
            <b class="text-tx">{{ total.toLocaleString() }}</b>
          </template>
          <template #time>
            <b class="text-tx">{{ runTime }}</b>
          </template>
        </i18n-t>
        <i18n-t v-else keypath="character.run.lineNoTotal" tag="span" class="data text-small text-dim">
          <template #n>
            <b class="text-tx">{{ w.target }}</b>
          </template>
        </i18n-t>
        <div class="spacer" />
        <button class="btn gh" @click="emit('close')">{{ $t('character.actions.cancel') }}</button>
        <button class="btn" @click="submit(false)">
          <Icon name="save" :size="14" />
          {{ $t('character.actions.saveOnly') }}
        </button>
        <button class="btn pri" @click="submit(true)">
          <Icon name="play" :size="14" />
          {{ $t('character.actions.saveRun', { n: w.target }) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: absolute;
  inset: 0;
  background: oklch(0 0 0 / 0.66);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 30;
}
.modal {
  width: min(1120px, 94%);
  max-height: 92%;
  display: flex;
  flex-direction: column;
  box-shadow: 0 32px 72px oklch(0 0 0 / 0.6);
}
.head {
  padding: 14px 20px;
}
.cols {
  display: grid;
  grid-template-columns: 1fr 300px;
  min-height: 0;
  overflow: auto;
}
.main-col {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  border-right: 1px solid var(--line-soft);
}
.side-col {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.align-start {
  align-items: start;
}
.sec {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sec-h {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.sec-h .spacer {
  flex: 1;
}
.src-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.sec.off > :not(.sec-h) {
  opacity: 0.55;
}
.sug-scroll {
  max-height: 280px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 6px;
  scrollbar-width: thin;
  scrollbar-color: var(--line) transparent;
}
.nm-group {
  display: flex;
  flex-direction: column;
}
.nm-h {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--dim);
  padding: 6px 0 4px;
}
.nm-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid var(--line-soft);
}
.nm-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.nm-text .jp {
  overflow-wrap: anywhere;
}
.nm-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
  font-size: 10px;
  color: var(--dim);
}
.nm-meta .lang {
  color: var(--mut);
}
.nm-meta .warn {
  color: var(--rose);
}
.nm-row.risky .jp {
  color: var(--mut);
}
.nm-add {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.more {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  padding: 4px 0;
  font-size: 11px;
  color: var(--mut);
  cursor: pointer;
}
.target-grid {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 18px;
  align-items: start;
}
.preset {
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.toggle {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.toggle label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
}
.cycle {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px solid var(--line-soft);
}
.cycle-bar {
  display: flex;
  height: 4px;
  background: var(--line-soft);
  overflow: hidden;
}
.cycle-bar .done {
  background: var(--mut);
}
.cycle-bar .now {
  background: var(--ember);
  min-width: 3px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  color: var(--mut);
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 6px;
  background: var(--dim);
}
.dot.now {
  background: var(--ember);
}
.runs {
  display: flex;
  flex-direction: column;
}
.run-row {
  display: grid;
  grid-template-columns: 52px 1fr auto;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid var(--line-soft);
  font-size: 12px;
  color: var(--mut);
}
.run-row.first {
  color: var(--tx);
}
.run-row.first .data {
  color: var(--ember);
}
/* a pixiv-only setting while pixiv is off: still editable, visibly idle */
.field.inert > :not(label) {
  opacity: 0.55;
}
.sec.off .n {
  color: var(--dim);
  border-color: var(--line);
}
.sec-h .n {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font: 600 11px var(--mono);
  color: var(--ember);
  border: 1px solid color-mix(in oklch, var(--ember) 45%, transparent);
  background: color-mix(in oklch, var(--ember) 15%, transparent);
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.row {
  display: grid;
  grid-template-columns: 1fr 220px auto;
  gap: 10px;
  align-items: center;
}
.row input[readonly] {
  background: var(--bg);
}
.row.bad input {
  border-color: color-mix(in oklch, var(--rose) 60%, transparent);
}
.stat {
  font-size: 12.5px;
}
.stat .ok {
  color: var(--moss);
}
.add {
  border-style: dashed;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.chips .term {
  width: 120px;
  height: 24px;
  padding: 0 9px;
  font-size: 12px;
}
.x {
  display: inline-flex;
  align-items: center;
  background: none;
  border: none;
  color: var(--dim);
  padding: 0 0 0 4px;
  cursor: pointer;
}
.strip {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}
.tile {
  aspect-ratio: 1;
  background: var(--surf2);
  overflow: hidden;
}
.tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.sug {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sug-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--line-soft);
  background: var(--surf2);
}
.sug-row.low {
  color: var(--dim);
  background: transparent;
}
.sug-row .add,
.nm-add .add {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: none;
  border: 0;
  color: var(--moss);
  font: 600 12px var(--font);
  padding: 0;
  cursor: pointer;
}
.foot {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 13px 20px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg);
}
</style>
