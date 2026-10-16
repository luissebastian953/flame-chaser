<script setup lang="ts">
import type { Job, Lane, Watch } from '@/lib/types';

const lib = useLibrary();
const defaults = useCharacterDefaults();
const { t } = useI18n();
const jobs = useJobs();
const ep = useEndpoint();
const src = useSources();
const fm = useFormats();
const router = useRouter();
const editing = ref<Watch | null>(null);
const isNew = ref(false);
const status = reactive({ msg: '' });

const RUNS = 8; // bars in the run history
const TICKS = 20; // the posts-per-run ruler
const TARGET_MAX = 1000; // posts per character per crawl (coreflame/handlers.py TARGET_MAX)
const SHOWN_CHIPS = 2; // tags or terms a row shows before "+N more"

onMounted(() => Promise.all([lib.loadWatches(), jobs.load().catch(() => {})]));

// -- crawl status cards -------------------------------------------------------
// the daemon lists jobs newest first; a crawl that ended in any state is a run
const runs = computed(() => jobs.jobs.filter((j) => j.type === 'poll' && j.finished_at).slice(0, RUNS));
const last = computed(() => runs.value[0] ?? null);
const count = (j: Job | null, key: string) => j?.counters[key] ?? 0;

// bar heights in px, oldest on the left and the latest run lit on the right;
// always RUNS slots, the ones before the first crawl left empty
const history = computed(() => {
  const n = runs.value.map((j) => count(j, 'downloaded')).reverse();
  const max = Math.max(1, ...n);
  const px = n.map((v) => Math.max(2, Math.round((v / max) * 30)));

  return [...Array<number | null>(RUNS - px.length).fill(null), ...px];
});

const checked = computed(() => runs.value.reduce((n, j) => n + count(j, 'listed'), 0));

// "4m ago" keeps up while the page is open
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval> | undefined;
onMounted(() => (clock = setInterval(() => (now.value = Date.now()), 30_000)));
onUnmounted(() => clearInterval(clock));

function ago(iso: string | null) {
  if (!iso) return t('crawl.cards.ago.never');
  const m = Math.max(0, Math.round((now.value - new Date(iso).getTime()) / 60_000));
  if (m < 1) return t('crawl.cards.ago.justNow');
  if (m < 60) return t('crawl.cards.ago.minutes', { n: m });
  if (m < 48 * 60) return t('crawl.cards.ago.hours', { n: Math.round(m / 60) });

  return t('crawl.cards.ago.days', { n: Math.round(m / 1440) });
}

// posts per run: one number when every character agrees, a range otherwise
const targets = computed(() => lib.watches.map((w) => w.target ?? 100));
const targetHi = computed(() => (targets.value.length ? Math.max(...targets.value) : 0));

const perRun = computed(() => {
  if (!targets.value.length) return '—';
  const lo = Math.min(...targets.value);

  return lo === targetHi.value ? fm.number(lo) : `${fm.number(lo)}–${fm.number(targetHi.value)}`;
});

const lit = computed(() => Math.round((targetHi.value / TARGET_MAX) * TICKS));

// recognition: what the last crawl kept against what its image filter threw away
const kept = computed(() => count(last.value, 'downloaded'));
const dropped = computed(() => count(last.value, 'rejected'));

const keptShare = computed(() =>
  kept.value + dropped.value ? Math.round((kept.value / (kept.value + dropped.value)) * 100) : null,
);

const pixivState = computed(() =>
  src.pixivOk
    ? 'valid'
    : src.pixivPending
      ? 'checking'
      : src.status?.pixiv.verified === false
        ? 'expired'
        : 'notLinked',
);

const xState = computed(() => (src.twitterOk ? 'connected' : 'notLinked'));
const tone = (s: string) => (s === 'valid' || s === 'connected' ? 'moss' : s === 'expired' ? 'rose' : 'dim');

// -- watched characters -------------------------------------------------------
function add() {
  editing.value = {
    slug: '',
    label: '',
    pixiv_tags: [],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv', 'twitter'],
    target: 100,
    kind_filter: true,
    gender: defaults.gender,
    gender_mode: defaults.gender_mode,
  };

  isNew.value = true;
}

function edit(w: Watch) {
  editing.value = {
    ...w,
    pixiv_tags: [...w.pixiv_tags],
    match_terms: [...w.match_terms],
    sources: [...(w.sources ?? ['pixiv', 'twitter'])],
  };

  isNew.value = false;
}

async function saved(w: Watch, runNow: boolean) {
  const r = await lib.saveWatch(w, isNew.value);
  status.msg = r.reopened ? t('crawl.status.reopened', { n: r.reopened }) : t('crawl.status.saved');
  editing.value = null;
  if (runNow) await run(w.slug);
}

/** Each character crawls to its own posts-per-run (set in its form). One
 *  character's run stays here -- its row shows the job; Run all opens the
 *  pipeline, which is where a whole-archive crawl is watched. */
async function run(slug?: string) {
  await jobs.submit('poll', slug ? { watches: [slug] } : {});
  if (!slug) router.push('/pipeline');
}

const RECENT_MS = 60_000; // "done" stays on the row this long after a job ends

/** What a character's row says about its jobs: the running one first, else
 *  queued, else one that just finished. */
function rowState(
  slug: string,
): { kind: 'running' | 'queued' | 'done' | 'failed'; job: Job; n: number } | null {
  const mine = jobs.jobs.filter((j) => Array.isArray(j.params.watches) && j.params.watches.includes(slug));
  const running = mine.find((j) => j.state === 'running');
  if (running) return { kind: 'running', job: running, n: 1 };
  const queued = mine.filter((j) => j.state === 'queued');
  if (queued.length) return { kind: 'queued', job: queued[0]!, n: queued.length };

  const recent = mine
    .filter((j) => j.finished_at && Date.now() - new Date(j.finished_at).getTime() < RECENT_MS)
    .sort((a, b) => (b.finished_at ?? '').localeCompare(a.finished_at ?? ''))[0];

  if (!recent) return null;
  return { kind: recent.state === 'succeeded' ? 'done' : 'failed', job: recent, n: 1 };
}

function rowColor(j: Job): string {
  return workerColor(workerIndex(j.worker ?? (j.lane === 'any' ? null : j.lane), lanes.value));
}

const lanes = computed<Lane[]>(() => jobs.pipeline?.workers.map((w) => w.lane) ?? ['pixiv', 'twitter']);
</script>

<template>
  <div class="top">
    <div>
      <div class="h1">{{ $t('crawl.title') }}</div>
      <div class="sub">
        {{
          $t('crawl.subtitle', {
            characters: lib.watches.length,
            tags: lib.watches.reduce((n, w) => n + w.pixiv_tags.length, 0),
          })
        }}
      </div>
    </div>
    <div class="spacer" />
    <span v-if="status.msg" class="kv">{{ status.msg }}</span>
    <button class="btn gh" @click="add">
      <Icon name="plus" :size="14" />
      {{ $t('crawl.addCharacter') }}
    </button>
    <button class="btn pri" :disabled="!lib.watches.length" @click="run()">
      <Icon name="play" :size="14" />
      {{ $t('crawl.runAll') }}
    </button>
  </div>
  <div class="body">
    <div class="cards">
      <StatCard decorated-border>
        <div class="chead">
          <span class="ptitle">{{ $t('crawl.cards.lastRun.title') }}</span>
          <span class="meta">{{ ago(last?.finished_at ?? null) }}</span>
        </div>
        <div class="row">
          <div class="big">
            <b class="ember">{{ last ? $t('crawl.cards.lastRun.plus', { n: fm.number(kept) }) : '—' }}</b>
            <span>{{ $t('crawl.cards.lastRun.unit') }}</span>
          </div>
          <div class="bars" aria-hidden="true">
            <i
              v-for="(h, i) in history"
              :key="i"
              :class="{ now: h !== null && i === RUNS - 1, none: h === null }"
              :style="h === null ? undefined : { height: `${h}px` }"
            />
          </div>
        </div>
        <div class="foot">
          <template v-if="runs.length">
            <b>{{ fm.number(checked) }}</b>
            {{
              $t(
                'crawl.cards.lastRun.foot',
                { runs: $t('crawl.cards.runCount', { n: runs.length }, runs.length) },
                checked,
              )
            }}
          </template>
          <template v-else>{{ $t('crawl.cards.lastRun.none') }}</template>
        </div>
      </StatCard>

      <StatCard decorated-border>
        <div class="chead">
          <span class="ptitle">{{ $t('crawl.cards.perRun.title') }}</span>
          <span class="meta">{{ $t('crawl.cards.perRun.max', { n: fm.number(TARGET_MAX) }) }}</span>
        </div>
        <div class="big">
          <b>{{ perRun }}</b>
          <span>{{ $t('crawl.cards.perRun.unit') }}</span>
        </div>
        <div class="ruler" aria-hidden="true">
          <i v-for="i in TICKS" :key="i" :class="{ on: i <= lit }" />
        </div>
        <div class="foot">{{ $t('crawl.cards.perRun.foot') }}</div>
      </StatCard>

      <StatCard decorated-border>
        <div class="chead">
          <span class="ptitle">{{ $t('crawl.cards.recognition.title') }}</span>
          <span class="meta">{{ $t('crawl.cards.recognition.meta') }}</span>
        </div>
        <div class="big">
          <b class="cyan">
            {{ keptShare === null ? '—' : $t('crawl.cards.recognition.share', { n: keptShare }) }}
          </b>
          <span>{{ $t('crawl.cards.recognition.unit') }}</span>
        </div>
        <div class="split" aria-hidden="true">
          <i class="kept" :style="{ flex: kept }" />
          <i class="drop" :style="{ flex: dropped }" />
        </div>
        <div class="foot">
          <b class="moss">{{ fm.number(kept) }}</b>
          {{ $t('crawl.cards.recognition.kept') }}
          <b class="rose">{{ fm.number(dropped) }}</b>
          {{ $t('crawl.cards.recognition.dropped') }}
        </div>
      </StatCard>

      <StatCard decorated-border>
        <div class="chead">
          <span class="ptitle">{{ $t('crawl.cards.sources.title') }}</span>
          <RouterLink to="/settings" class="link">{{ $t('crawl.cards.sources.settings') }}</RouterLink>
        </div>
        <div class="srcs">
          <div>
            <i class="dot" :class="tone(pixivState)" />
            {{ $t('crawl.table.sourcePixiv') }}
            <span class="st">{{ $t(`crawl.cards.sources.state.${pixivState}`) }}</span>
          </div>
          <div>
            <i class="dot" :class="tone(xState)" />
            {{ $t('crawl.table.sourceX') }}
            <span class="st">{{ $t(`crawl.cards.sources.state.${xState}`) }}</span>
          </div>
          <div>
            <i class="dot" :class="ep.health ? 'moss' : 'dim'" />
            {{ $t('crawl.cards.sources.library') }}
            <span class="st">
              {{
                ep.health
                  ? $t('crawl.cards.sources.free', { n: fm.bytes(ep.health.library_free_bytes) })
                  : '—'
              }}
            </span>
          </div>
        </div>
      </StatCard>
    </div>

    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('crawl.table.heading') }}</span>
      </div>
      <table v-if="lib.watches.length">
        <thead>
          <tr>
            <th>{{ $t('crawl.table.character') }}</th>
            <th>{{ $t('crawl.table.sources') }}</th>
            <th>{{ $t('crawl.table.pixivTags') }}</th>
            <th>{{ $t('crawl.table.matchTerms') }}</th>
            <th>{{ $t('crawl.table.bookmarks') }}</th>
            <th>{{ $t('crawl.table.r18') }}</th>
            <th>{{ $t('crawl.table.posts') }}</th>
            <th>{{ $t('crawl.table.perRun') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in lib.watches" :key="w.slug">
            <td>
              <b>{{ w.label || w.slug }}</b>
              <div class="kv mono">{{ w.slug }}</div>
            </td>
            <td style="white-space: nowrap">
              <span
                class="chip"
                :class="w.sources.includes('pixiv') ? 'on' : 'off'"
                style="margin-right: 4px"
              >
                {{ $t('crawl.table.sourcePixiv') }}
              </span>
              <span class="chip" :class="w.sources.includes('twitter') ? 'on' : 'off'">
                {{ $t('crawl.table.sourceX') }}
              </span>
            </td>
            <td>
              <div class="chips" :class="{ more: w.pixiv_tags.length > SHOWN_CHIPS }">
                <span v-for="tag in w.pixiv_tags" :key="tag" class="chip jp">{{ tag }}</span>
                <button v-if="w.pixiv_tags.length > SHOWN_CHIPS" class="morelbl" @click="edit(w)">
                  {{ $t('crawl.table.more', { n: w.pixiv_tags.length - SHOWN_CHIPS }) }}
                </button>
              </div>
            </td>
            <td>
              <div class="chips" :class="{ more: w.match_terms.length > SHOWN_CHIPS }">
                <span v-for="term in w.match_terms" :key="term" class="chip mono">{{ term }}</span>
                <button v-if="w.match_terms.length > SHOWN_CHIPS" class="morelbl" @click="edit(w)">
                  {{ $t('crawl.table.more', { n: w.match_terms.length - SHOWN_CHIPS }) }}
                </button>
              </div>
            </td>
            <td class="num">{{ w.min_bookmarks }}</td>
            <td>{{ w.include_r18 ? $t('crawl.table.r18On') : $t('crawl.table.r18Off') }}</td>
            <td class="num">{{ w.post_count ?? 0 }}</td>
            <td class="num">{{ w.target ?? 100 }}</td>
            <td>
              <div class="actions">
                <button class="btn gh sm" @click="edit(w)">
                  <Icon name="edit" :size="12" />
                  {{ $t('crawl.edit') }}
                </button>
                <RouterLink
                  v-if="rowState(w.slug)?.kind === 'running'"
                  :to="`/pipeline/${rowState(w.slug)!.job.worker ?? 'pixiv'}`"
                  class="chip live"
                  :style="{ '--wc': rowColor(rowState(w.slug)!.job) }"
                >
                  <Icon name="loader" class="spin" :size="11" />
                  {{
                    $t('crawl.row.running', {
                      stage: rowState(w.slug)!.job.stage ?? '',
                      posts: postsOf(rowState(w.slug)!.job),
                    })
                  }}
                </RouterLink>
                <RouterLink v-else-if="rowState(w.slug)?.kind === 'queued'" to="/pipeline" class="chip off">
                  <Icon name="clock" :size="11" />
                  {{ $t('crawl.row.queued', { n: rowState(w.slug)!.n }, rowState(w.slug)!.n) }}
                </RouterLink>
                <template v-else>
                  <span v-if="rowState(w.slug)?.kind === 'done'" class="chip ok">
                    <Icon name="check" :size="11" />
                    {{ $t('crawl.row.done', { n: postsOf(rowState(w.slug)!.job) }) }}
                  </span>
                  <span v-else-if="rowState(w.slug)?.kind === 'failed'" class="chip err">
                    <Icon name="error" :size="11" />
                    {{ $t('crawl.row.failed') }}
                  </span>
                  <button class="btn gh sm" @click="run(w.slug)">
                    <Icon name="play" :size="12" />
                    {{ $t('crawl.run') }}
                  </button>
                </template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">{{ $t('crawl.empty') }}</div>
    </div>
  </div>
  <WatchForm v-if="editing" :watch="editing" :is-new="isNew" @save="saved" @close="editing = null" />
</template>

<style scoped>
/* ---- crawl status cards ---- */
.cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.chead {
  display: flex;
  align-items: center;
  gap: 9px;
}
.chead .ptitle {
  font-size: 10px;
  letter-spacing: 0.09em;
}
.meta {
  margin-left: auto;
  font: 10.5px var(--font-mono);
  color: var(--color-dim);
  white-space: nowrap;
}
.link {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-cyan);
  white-space: nowrap;
}
.row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.big {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.big b {
  font: 600 26px/1 var(--font-sans);
  letter-spacing: -0.01em;
}
.big span {
  font-size: 12px;
  color: var(--color-mut);
  white-space: nowrap;
}
.ember {
  color: var(--color-ember);
}
.cyan {
  color: var(--color-cyan);
}
.moss {
  color: var(--color-moss);
}
.rose {
  color: var(--color-rose);
}
.foot {
  margin-top: auto;
  font: 11px var(--font-mono);
  color: var(--color-dim);
}
.foot b {
  color: var(--color-tx);
  font-weight: 500;
}
.foot b.moss {
  color: var(--color-moss);
}
.foot b.rose {
  color: var(--color-rose);
  margin-left: 6px;
}
/* run history: a bar per crawl, bottom-aligned, the latest lit */
.bars {
  flex: none;
  margin-left: auto;
  display: flex;
  align-items: flex-end;
  gap: 3px;
  width: 56px;
  height: 30px;
}
.bars i {
  flex: 1;
  background: oklch(0.33 0.024 265);
}
.bars i.none {
  background: transparent;
}
.bars i.now {
  background: var(--color-ember);
  box-shadow: 0 0 8px oklch(0.74 0.205 332 / 0.6);
}
/* posts per run on a 20-tick ruler to the 1,000 cap */
.ruler {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 8px;
}
.ruler i {
  flex: 1;
  height: 5px;
  background: oklch(0.3 0.024 265);
}
.ruler i:nth-child(5n) {
  height: 8px;
}
.ruler i.on {
  background: var(--color-cyan);
}
/* kept against dropped, weighted by count */
.split {
  display: flex;
  gap: 2px;
  height: 5px;
}
.split .kept {
  background: var(--color-moss);
}
.split .drop {
  background: var(--color-rose);
  opacity: 0.75;
}
.srcs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12.5px;
}
.srcs > div {
  display: flex;
  align-items: center;
  gap: 8px;
}
.srcs .st {
  margin-left: auto;
  font: 10.5px var(--font-mono);
  color: var(--color-dim);
}
.dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.dot.dim {
  color: var(--color-dim);
  box-shadow: none;
}

/* ---- watched characters ---- */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
/* more than two: one clipped line fading into the panel, with the count on top */
.chips.more {
  position: relative;
  flex-wrap: nowrap;
  overflow: hidden;
  width: 200px;
  max-width: 100%;
}
.chips.more .chip {
  flex: none;
}
.chips.more::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent 30%, var(--color-surf) 78%);
  pointer-events: none;
}
.morelbl {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 1;
  padding: 0 0 0 4px;
  border: 0;
  background: var(--color-surf); /* the fade's end colour: keeps the count legible over a long chip */
  font: 600 10.5px var(--font-mono);
  letter-spacing: 0.04em;
  color: var(--color-ember);
  white-space: nowrap;
  cursor: pointer;
}
.actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
}
/* the row's job: a chip in its worker's colour, a link into the pipeline */
.actions .chip {
  height: 25px;
  font-size: 11px;
  white-space: nowrap;
  text-decoration: none;
}
.actions .chip.live {
  color: var(--wc);
  border-color: var(--wc);
  background: color-mix(in oklch, var(--wc) 12%, var(--color-bg));
  box-shadow: 0 0 8px color-mix(in oklch, var(--wc) 35%, transparent);
}
.actions .chip.ok {
  color: var(--color-moss);
  border-color: color-mix(in oklch, var(--color-moss) 45%, transparent);
}
</style>
