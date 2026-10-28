<script setup lang="ts">
/**
 * Crawl pipeline, list state: one card per worker (pixiv, X), the queue,
 * today's finished jobs; rate budget, session totals and activity on the
 * right. Open a card for that worker's stages, counters and log.
 */
import type { DaemonEvent } from '@/lib/api';
import type { Job, Lane } from '@/lib/types';

const jobs = useJobs();
const lib = useLibrary();
const router = useRouter();
const { t } = useI18n();
usePipelineLive();

const lanes = computed(() => jobs.lanes);

interface Slot {
  lane: Lane;
  index: number;
  color: string;
  job: Job | null;
}

const slots = computed<Slot[]>(() =>
  jobs.slots.map((s, index) => ({ lane: s.lane, index, color: workerColor(index), job: s.job })),
);

const busy = computed(() => slots.value.filter((s) => s.job));
const idle = computed(() => slots.value.filter((s) => !s.job));
const focused = computed(() => jobs.focus ?? busy.value[0]?.lane ?? null);
const anyRunning = computed(() => busy.value.length > 0);

const pill = computed(() =>
  jobs.offline ? 'offline' : jobs.pipeline?.paused ? 'paused' : anyRunning.value ? 'running' : 'idle',
);

function open(lane: Lane) {
  jobs.focus = lane;
  router.push(`/pipeline/${lane}`);
}

function name(j: Job) {
  const ch = characterOf(j, lib.watches);
  if (ch) return ch;
  const tt = jobTitle(j);
  return { slug: null, name: t(tt.key, tt.params), jp: null, cover: null };
}

function sourcesOf(j: Job): Lane[] {
  const ch = characterOf(j, lib.watches);
  const w = ch ? lib.watches.find((x) => x.slug === ch.slug) : null;
  if (w) return w.sources;
  const s = sourceOf(j);
  return s ? [s] : [];
}

function pct(j: Job): number | null {
  if (j.total === null || j.total === 0) return null;
  return Math.min(100, Math.round((100 * j.done) / j.total));
}

/** the job's latest line, as the progress label */
function lastLine(j: Job): string {
  for (let i = jobs.events.length - 1; i >= 0; i--) {
    const e = jobs.events[i]!;
    if (e.data.job_id === j.id && (e.type === 'job.item' || e.type === 'job.log' || e.type === 'job.stage')) {
      return String(e.data.message ?? '');
    }
  }
  return j.stage ? t(`pipeline.stage.${j.stage}`) : '';
}

// cancel all: a second click within 4s confirms
const armed = ref(false);

function cancelAll() {
  if (!armed.value) {
    armed.value = true;
    setTimeout(() => (armed.value = false), 4000);
    return;
  }
  armed.value = false;
  jobs.cancelAll().catch(() => {});
}

const showAll = ref(false);
const completed = computed(() => (showAll.value ? jobs.runsToday : jobs.runsToday.slice(0, 5)));
/** runs unfolded into their parts */
const unfolded = ref(new Set<string>());

function unfold(id: string) {
  const next = new Set(unfolded.value);
  if (!next.delete(id)) next.add(id);
  unfolded.value = next;
}

/** a part's name: the source half of the crawl, or the sweep */
function partKey(p: Job): string {
  if (p.type === 'timelines') return 'pipeline.job.timelines';
  return sourceOf(p) === 'twitter' ? 'pipeline.lane.twitter' : 'pipeline.lane.pixiv';
}

function partColor(p: Job): string {
  return workerColor(workerIndex(p.worker ?? (p.lane === 'any' ? null : p.lane), lanes.value));
}

function tally(j: Job): { new: number; kept: number; dropped: number } {
  const c = j.counters ?? {};
  return {
    new: Number(c.new_posts ?? c.new ?? 0),
    kept: Number(c.downloaded ?? 0),
    dropped: Number(c.rejected ?? 0),
  };
}

const laneByJob = computed(() => new Map(jobs.jobs.map((j) => [j.id, j.worker ?? j.lane])));

const activity = computed(() =>
  jobs.events
    .filter((e: DaemonEvent) => e.type === 'job.item' || e.type === 'job.log')
    .slice(-30)
    .reverse(),
);

function dotColor(e: DaemonEvent): string {
  const lane = laneByJob.value.get(String(e.data.job_id ?? ''));
  return lane && lane !== 'any' ? workerColor(workerIndex(lane, lanes.value)) : 'var(--dim)';
}
</script>

<template>
  <div class="screen" :data-pipeline-running="anyRunning ? 'true' : 'false'">
    <EmberField :active="jobs.burning" />
    <div class="top">
      <div>
        <div class="flex items-center gap-10">
          <div class="h1">{{ $t('pipeline.title') }}</div>
          <span class="pill" :class="pill === 'offline' ? 'paused' : pill">
            <i class="dot" />
            {{ $t(`pipeline.pill.${pill}`) }}
          </span>
        </div>
        <div class="sub">
          {{
            $t('pipeline.sub', {
              busy: busy.length,
              total: slots.length,
              queued: $t('pipeline.queuedCount', jobs.queued.length),
            })
          }}
        </div>
        <div v-if="jobs.offline" class="sub offline">{{ $t('pipeline.offlineHint') }}</div>
      </div>
      <div class="spacer" />
      <span class="num">{{ $t('pipeline.reqPerMin', { n: jobs.pipeline?.req_per_min ?? 0 }) }}</span>
      <button
        class="btn gh"
        :disabled="!jobs.pipeline?.paused && !anyRunning && !jobs.queued.length"
        @click="jobs.pauseQueue(!jobs.pipeline?.paused)"
      >
        <Icon :name="jobs.pipeline?.paused ? 'play' : 'pause'" :size="13" />
        {{ jobs.pipeline?.paused ? $t('pipeline.resumeQueue') : $t('pipeline.pauseQueue') }}
      </button>
      <button class="btn danger" :disabled="!anyRunning && !jobs.queued.length" @click="cancelAll">
        <Icon name="stop" :size="13" />
        {{ armed ? $t('pipeline.cancelAllConfirm') : $t('pipeline.cancelAll') }}
      </button>
    </div>

    <div class="body grid2">
      <div class="col">
        <section>
          <div class="label-row">
            <span class="ptitle">{{ $t('pipeline.running') }}</span>
            <span class="kv">{{ $t('pipeline.runningHint') }}</span>
          </div>
          <div class="cards">
            <div
              v-for="s in busy"
              :key="s.lane"
              class="panel card"
              :class="{ focused: focused === s.lane }"
              :style="{ '--wc': s.color }"
              role="button"
              tabindex="0"
              @click="open(s.lane)"
              @keydown.enter="open(s.lane)"
            >
              <span class="mono widx">{{ s.index + 1 }}</span>
              <WorkerAvatar :sha="name(s.job!).cover" :color="s.color" :size="40" />
              <div class="who">
                <div class="nm">
                  <b>{{ name(s.job!).name }}</b>
                  <span v-if="name(s.job!).jp" class="jp">{{ name(s.job!).jp }}</span>
                </div>
                <div class="srcs">
                  <span
                    v-for="src in sourcesOf(s.job!)"
                    :key="src"
                    class="chip mono src"
                    :class="{ cur: src === sourceOf(s.job!) }"
                  >
                    {{ $t(`pipeline.lane.${src}`) }}
                  </span>
                  <span v-if="s.job!.paused" class="chip mono src paused">
                    {{ $t('pipeline.pausedTag') }}
                  </span>
                </div>
              </div>
              <div class="track">
                <div class="segs">
                  <i
                    v-for="(st, si) in stagesOf(s.job!)"
                    :key="st"
                    :class="si < stageIndex(s.job!) ? 'done' : si === stageIndex(s.job!) ? 'act' : 'todo'"
                  />
                </div>
                <div class="stg">
                  <span class="sname">{{ s.job!.stage ? $t(`pipeline.stage.${s.job!.stage}`) : '' }}</span>
                  <span class="mono dim">
                    {{ Math.min(stageIndex(s.job!) + 1, stagesOf(s.job!).length) }}/{{
                      stagesOf(s.job!).length
                    }}
                  </span>
                </div>
              </div>
              <div class="prog">
                <div class="plbl">
                  <span class="pl">{{ lastLine(s.job!) }}</span>
                  <span class="num pv">
                    {{ s.job!.total !== null ? `${s.job!.done} / ${s.job!.total}` : s.job!.done }}
                  </span>
                </div>
                <div class="pbar" :class="{ indet: pct(s.job!) === null }">
                  <div :style="{ width: (pct(s.job!) ?? 30) + '%' }" />
                </div>
              </div>
              <div class="count">
                <div class="big">
                  <template v-if="targetOf(s.job!) !== null">
                    <span class="mine">{{ postsOf(s.job!) }}</span>
                    <span class="of">&nbsp;/ {{ targetOf(s.job!) }}</span>
                  </template>
                  <span v-else class="mine">{{ $t('pipeline.postsNew', { posts: postsOf(s.job!) }) }}</span>
                </div>
                <div class="kv">{{ $t('pipeline.reqPerMin', { n: s.job!.req_per_min ?? 0 }) }}</div>
              </div>
              <button class="btn sm" :class="focused === s.lane ? 'pri' : 'gh'" @click.stop="open(s.lane)">
                {{ $t('pipeline.open') }}
              </button>
            </div>
            <div v-for="s in idle" :key="s.lane" class="idle">
              <span class="mono widx">{{ s.index + 1 }}</span>
              {{ $t('pipeline.idleWorker', { lane: $t(`pipeline.lane.${s.lane}`) }) }}
            </div>
          </div>
        </section>

        <div class="panel">
          <QueuedPanel />
        </div>

        <div class="panel grow">
          <div class="phead">
            <span class="ptitle">{{ $t('pipeline.completed') }}</span>
            <div class="spacer" />
            <button v-if="jobs.runsToday.length > 5" class="kv linkish" @click="showAll = !showAll">
              {{ showAll ? $t('pipeline.seeFewer') : $t('pipeline.seeAll', { n: jobs.runsToday.length }) }}
            </button>
          </div>
          <div v-if="completed.length" class="done-rows">
            <template v-for="r in completed" :key="r.id">
              <button
                class="drow"
                :class="{ open: unfolded.has(r.id) }"
                :aria-expanded="unfolded.has(r.id)"
                :title="$t('pipeline.parts')"
                @click="unfold(r.id)"
              >
                <Icon name="chevron-right" :size="12" class="chev" />
                <WorkerAvatar :sha="name(r.jobs[0]!).cover" :size="22" :ring="false" class="faded" />
                <b class="dn">{{ name(r.jobs[0]!).name }}</b>
                <span v-if="name(r.jobs[0]!).jp" class="jp">{{ name(r.jobs[0]!).jp }}</span>
                <span
                  v-if="r.state !== 'succeeded'"
                  class="st"
                  :class="r.state"
                  :title="r.error ?? undefined"
                >
                  {{ $t(`pipeline.state.${r.state}`) }}
                </span>
                <div class="spacer" />
                <i18n-t keypath="pipeline.completedRow" tag="span" class="kv tallies">
                  <template #new>
                    <span class="ok">{{ r.counters.new }}</span>
                  </template>
                  <template #kept>
                    <b>{{ r.counters.kept }}</b>
                  </template>
                  <template #dropped>
                    <span class="err">{{ r.counters.dropped }}</span>
                  </template>
                </i18n-t>
                <span class="num tm">{{ clock(r.finished_at).slice(0, 5) }}</span>
              </button>
              <div v-if="unfolded.has(r.id)" class="parts">
                <div v-for="p in r.parts" :key="p.id" class="prow">
                  <i class="dot" :style="{ background: partColor(p) }" />
                  <span class="pn">{{ $t(partKey(p)) }}</span>
                  <span
                    v-if="p.state !== 'succeeded'"
                    class="st"
                    :class="p.state"
                    :title="p.error ?? undefined"
                  >
                    {{ $t(`pipeline.state.${p.state}`) }}
                  </span>
                  <div class="spacer" />
                  <i18n-t keypath="pipeline.completedRow" tag="span" class="kv tallies">
                    <template #new>
                      <span class="ok">{{ tally(p).new }}</span>
                    </template>
                    <template #kept>
                      <b>{{ tally(p).kept }}</b>
                    </template>
                    <template #dropped>
                      <span class="err">{{ tally(p).dropped }}</span>
                    </template>
                  </i18n-t>
                  <span class="num tm">{{ clock(p.finished_at).slice(0, 5) }}</span>
                </div>
              </div>
            </template>
          </div>
          <div v-else class="kv pad">{{ $t('pipeline.noneToday') }}</div>
        </div>
      </div>

      <div class="panel side">
        <RateBudget />
        <div class="phead">
          <span class="ptitle">{{ $t('pipeline.session.title') }}</span>
        </div>
        <div class="session">
          <div>
            <b class="ember">+{{ jobs.session.images.toLocaleString() }}</b>
            <span>{{ $t('pipeline.session.images') }}</span>
          </div>
          <div>
            <b>{{ jobs.session.checked.toLocaleString() }}</b>
            <span>{{ $t('pipeline.session.checked') }}</span>
          </div>
          <div>
            <b class="cyan">{{ jobs.session.dupes.toLocaleString() }}</b>
            <span>{{ $t('pipeline.session.dupes') }}</span>
          </div>
          <div>
            <b class="rose">{{ jobs.session.dropped.toLocaleString() }}</b>
            <span>{{ $t('pipeline.session.dropped') }}</span>
          </div>
        </div>
        <div class="phead">
          <span class="ptitle">{{ $t('pipeline.activity.title') }}</span>
          <div class="spacer" />
          <span class="kv">{{ $t('pipeline.activity.hint') }}</span>
        </div>
        <div class="feed mono">
          <div v-for="e in activity" :key="e.id" class="arow">
            <span class="t">{{ clock(String(e.data.at ?? '')) }}</span>
            <i class="adot" :style="{ background: dotColor(e) }" />
            <span class="k" :class="activityKind(e)">{{ activityKind(e) }}</span>
            <span class="m">{{ e.data.message }}</span>
          </div>
          <div v-if="!activity.length" class="kv">{{ $t('pipeline.activity.empty') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.screen {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.top,
.body {
  position: relative;
  z-index: 1;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 20px;
  padding: 0 8px;
  font: 600 10px var(--font);
  letter-spacing: 0.09em;
  text-transform: uppercase;
  border: 1px solid var(--line);
  color: var(--dim);
}
.pill .dot {
  width: 6px;
  height: 6px;
  background: currentColor;
}
.pill.running {
  color: var(--moss);
  border-color: color-mix(in oklch, var(--moss) 45%, transparent);
  background: color-mix(in oklch, var(--moss) 10%, transparent);
}
.pill.running .dot {
  box-shadow: 0 0 6px var(--moss);
}
.pill.paused {
  color: oklch(0.8 0.15 75);
  border-color: color-mix(in oklch, oklch(0.8 0.15 75) 45%, transparent);
}
.sub.offline {
  margin-top: 4px;
  max-width: 62ch;
  color: oklch(0.8 0.15 75);
}
.grid2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 366px;
  gap: 14px;
  align-items: start;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.grow {
  flex: 1;
}
.label-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card {
  padding: 13px 15px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.card.focused {
  border-color: var(--wc);
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--wc) 35%, transparent);
}
.widx {
  flex: 0 0 10px;
  font-size: 10px;
  color: var(--dim);
}
.who {
  flex: 0 0 126px;
  min-width: 0;
}
.nm {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nm b {
  font-weight: 600;
  font-size: 14px;
}
.jp {
  font-family: var(--font-jp);
  font-size: 13px;
  color: var(--mut);
  margin-left: 6px;
}
.srcs {
  display: flex;
  gap: 4px;
  margin-top: 4px;
}
.src {
  height: 17px;
  padding: 0 6px;
  font-size: 10px;
  color: var(--mut);
}
.src.cur {
  border-color: var(--wc);
}
.src.paused {
  color: oklch(0.8 0.15 75);
}
.track {
  flex: 0 0 124px;
  margin-right: 12px;
}
.segs {
  display: flex;
  gap: 3px;
}
.segs i {
  flex: 1;
  height: 4px;
}
.segs .done {
  background: oklch(0.55 0.024 265);
}
.segs .act {
  background: var(--wc);
  box-shadow: 0 0 6px var(--wc);
}
.segs .todo {
  border: 1px solid oklch(0.36 0.024 265);
}
.stg {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
}
.sname {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--wc);
}
.dim {
  font-size: 10px;
  color: var(--dim);
}
/* the progress block grows with the card but never past ~300px: a long log
   line ellipsizes instead of stretching it; the counter and Open stay right */
.prog {
  flex: 1 1 0;
  min-width: 130px;
  max-width: 300px;
  display: flex;
  flex-direction: column-reverse; /* the bar on top, the line under it */
}
.plbl {
  display: flex;
  gap: 8px;
  font-size: 12px;
}
.pl {
  color: var(--mut);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pv {
  flex: none;
  margin-left: auto;
}
.pbar {
  height: 3px;
  margin-bottom: 6px;
  background: var(--surf2);
  overflow: hidden;
}
.pbar div {
  height: 100%;
  background: var(--wc);
  transition: width 0.3s;
}
.pbar.indet div {
  animation: slide 1.4s infinite linear;
}
@keyframes slide {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(400%);
  }
}
.count {
  flex: 0 0 84px;
  margin-left: auto;
  text-align: right;
}
.big {
  font: 600 18px var(--font);
  white-space: nowrap;
}
.big .mine {
  color: var(--wc);
}
.big .of {
  color: var(--dim);
  font-weight: 500;
}
.idle {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 17px;
  border: 1px dashed var(--line);
  font-size: 12.5px;
  color: var(--mut);
}
.done-rows .drow {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 13px;
  border: 0;
  border-bottom: 1px solid var(--line-soft);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.done-rows .drow:hover {
  background: color-mix(in oklch, var(--surf2) 60%, transparent);
}
.done-rows .drow:focus-visible {
  outline: 1px solid var(--ember);
  outline-offset: -1px;
}
.chev {
  flex: 0 0 auto;
  color: var(--dim);
  transition: transform 0.15s;
}
.drow.open .chev {
  transform: rotate(90deg);
}
/* the run unfolded: its pixiv half, its X half, the sweep that followed */
.parts {
  border-bottom: 1px solid var(--line-soft);
  background: color-mix(in oklch, var(--surf2) 35%, transparent);
}
.prow {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 13px 6px 48px;
  font-size: 12px;
}
.prow .dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
}
.pn {
  color: var(--tx);
}
@media (prefers-reduced-motion: reduce) {
  .chev {
    transition: none;
  }
}
.faded {
  opacity: 0.8;
}
.dn {
  font-weight: 600;
  font-size: 13px;
}
.st {
  font-size: 10.5px;
  color: var(--dim);
}
.st.failed,
.st.interrupted {
  color: var(--rose);
}
.tallies {
  white-space: nowrap;
}
.tm {
  flex: 0 0 56px;
  text-align: right;
}
.pad {
  padding: 12px 13px;
}
.linkish {
  background: none;
  border: none;
  cursor: pointer;
}
.linkish:hover {
  color: var(--tx);
}
.side {
  position: sticky;
  top: 0;
}
.session {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  padding: 14px 13px;
}
.session div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.session b {
  font: 600 22px var(--font);
}
.session span {
  font-size: 10.5px;
  color: var(--dim);
}
.ember {
  color: var(--ember);
}
.cyan {
  color: var(--cyan);
}
.rose {
  color: var(--rose);
}
.feed {
  padding: 8px 13px 12px;
  font-size: 10.5px;
  max-height: 320px;
  overflow: auto;
}
.arow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.arow .t {
  flex: none;
  color: var(--dim);
}
.adot {
  flex: none;
  width: 5px;
  height: 5px;
}
.arow .k {
  flex: none;
  color: var(--mut);
}
.k.new {
  color: var(--moss);
}
.k.dupe {
  color: var(--cyan);
}
.k.gone {
  color: var(--ember);
}
.k.warn {
  color: var(--rose);
}
.arow .m {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--mut);
}
@media (max-width: 1100px) {
  .grid2 {
    grid-template-columns: minmax(0, 1fr);
  }
  .side {
    position: static;
  }
}
</style>
