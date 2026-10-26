<script setup lang="ts">
/**
 * Crawl pipeline, detail state: one worker's job -- its stages, the visited
 * split, progress, counters and its own log. The multi-worker overview lives
 * in the list state only. With nothing running, the worker's last job shows.
 */
import type { Job, Lane, LogLine } from '@/lib/types';

const props = defineProps<{ lane: Lane }>();

const jobs = useJobs();
const lib = useLibrary();
const router = useRouter();
const { t } = useI18n();
const { now } = usePipelineLive();

const lanes = computed(() => jobs.lanes);
const index = computed(() => workerIndex(props.lane, lanes.value));
const color = computed(() => workerColor(index.value));
const job = computed<Job | null>(() => jobs.forWorker(props.lane));
const running = computed(() => job.value?.state === 'running');
const anyRunning = computed(() => jobs.running.length > 0);

onMounted(() => (jobs.focus = props.lane));

const who = computed(() => {
  const j = job.value;
  if (!j) return null;
  const ch = characterOf(j, lib.watches);
  if (ch) return ch;
  const tt = jobTitle(j);
  return { slug: null, name: t(tt.key, tt.params), jp: null, cover: null };
});

const what = computed(() => {
  const j = job.value;
  if (!j) return '';
  const w = lib.watches.find((x) => x.slug === who.value?.slug);
  const term = sourceOf(j) === 'twitter' ? w?.match_terms[0] : w?.pixiv_tags[0];
  return term ? t('pipeline.detail.tag', { tag: term }) : '';
});

const sub = computed(() => {
  const j = job.value;
  if (!j) return '';
  return [t(`pipeline.lane.${sourceOf(j) ?? props.lane}`), what.value, j.type].filter(Boolean).join(' · ');
});

const startedAt = computed(() => clock(job.value?.started_at));

const elapsedText = computed(() => {
  const j = job.value;
  if (!j?.started_at) return '-';
  const end = j.finished_at ? new Date(j.finished_at).getTime() : now.value;
  return elapsed(j.started_at, end);
});

// ---- counters
const c = computed(() => job.value?.counters ?? {});
const target = computed(() => (job.value ? targetOf(job.value) : null));
const posts = computed(() => (job.value ? postsOf(job.value) : 0));
const stages = computed(() => (job.value ? stagesOf(job.value) : []));
const at = computed(() => (job.value ? stageIndex(job.value) : 0));

const listed = computed(() => c.value.listed ?? 0);
const gated = computed(() => c.value.gated ?? 0);
const showSplit = computed(() => !!job.value && sourceOf(job.value) === 'pixiv' && listed.value > 0);

const pct = computed(() => {
  const j = job.value;
  if (!j || j.total === null || j.total === 0) return null;
  return Math.min(100, Math.round((100 * j.done) / j.total));
});

const eta = computed(() => {
  const j = job.value;
  if (!j?.started_at || !running.value) return null;
  const spent = (now.value - new Date(j.started_at).getTime()) / 1000;
  const s = etaSeconds(j.done, j.total, spent);
  return s === null ? null : elapsed(new Date(now.value - s * 1000).toISOString(), now.value);
});

const counters = computed(() => [
  { key: 'indexed', n: c.value.new_posts ?? c.value.new ?? 0, tone: 'moss' },
  { key: 'skipped', n: gated.value || (c.value.skipped ?? 0), tone: '' },
  { key: 'downloaded', n: c.value.downloaded ?? c.value.stored ?? 0, tone: '' },
  { key: 'dupes', n: c.value.dupes ?? c.value.dupe ?? 0, tone: 'cyan' },
  { key: 'dropped', n: c.value.rejected ?? 0, tone: 'rose' },
  { key: 'failed', n: c.value.failed ?? 0, tone: 'rose' },
]);

// ---- log: the job's stored tail, then live lines as they arrive
const history = ref<LogLine[]>([]);

watch(
  () => job.value?.id,
  async (id) => {
    history.value = [];
    if (!id) return;
    try {
      const full = await api.get<Job>(`/api/jobs/${id}`);
      if (job.value?.id === id) history.value = (full.log ?? []).filter((l) => l.kind !== 'progress');
    } catch {
      /* the live lines still arrive */
    }
  },
  { immediate: true },
);

interface Line {
  key: string;
  at: string;
  src: string;
  kind: string;
  message: string;
}

const lines = computed<Line[]>(() => {
  const id = job.value?.id;
  if (!id) return [];

  const out: Line[] = history.value.map((l) => ({
    key: `h${l.seq}`,
    at: l.at,
    src: String(l.data.source ?? (l.kind === 'item' ? '' : 'sys')),
    kind: String(l.data.action ?? (l.kind === 'log' ? l.level : l.kind)),
    message: l.message,
  }));

  const last = history.value.at(-1)?.at ?? '';
  for (const e of jobs.events) {
    if (e.data.job_id !== id || e.type === 'job.progress') continue;
    const when = String(e.data.at ?? '');
    if (when <= last) continue;

    out.push({
      key: `e${e.id}`,
      at: when,
      src: String(e.data.source ?? (e.type === 'job.item' ? '' : 'sys')),
      kind: String(e.data.action ?? e.data.level ?? e.type.split('.')[1]),
      message: String(e.data.message ?? ''),
    });
  }
  return out;
});

const logEl = ref<HTMLElement | null>(null);
const follow = ref(true);

watch(
  () => lines.value.length,
  async () => {
    if (!follow.value) return;
    await nextTick();
    logEl.value?.scrollTo(0, logEl.value.scrollHeight);
  },
);

function back() {
  router.push('/pipeline');
}
</script>

<template>
  <div class="screen" :data-pipeline-running="anyRunning ? 'true' : 'false'" :style="{ '--wc': color }">
    <EmberField v-if="anyRunning" />
    <div class="top">
      <button
        class="btn gh back"
        :title="$t('pipeline.detail.back')"
        :aria-label="$t('pipeline.detail.back')"
        @click="back"
      >
        <Icon name="chevron-left" :size="14" />
      </button>
      <div class="min-w-0">
        <div class="flex items-center gap-10">
          <div class="h1 title">
            {{ who?.name ?? $t(`pipeline.lane.${lane}`) }}
            <span v-if="who?.jp" class="jp">{{ who.jp }}</span>
          </div>
          <span class="pill">
            <i class="dot" />
            {{ $t('pipeline.detail.worker', { n: index + 1 }) }}
          </span>
        </div>
        <div v-if="job" class="sub">
          {{ sub }} · {{ $t('pipeline.started', { time: startedAt }) }} · {{ elapsedText }}
        </div>
      </div>
      <div class="spacer" />
      <span class="num">{{ $t('pipeline.reqPerMin', { n: job?.req_per_min ?? 0 }) }}</span>
      <button class="btn gh" :disabled="!running" @click="job && jobs.pauseJob(job.id, !job.paused)">
        <Icon :name="job?.paused ? 'play' : 'pause'" :size="13" />
        {{ job?.paused ? $t('pipeline.detail.resumeWorker') : $t('pipeline.detail.pauseWorker') }}
      </button>
      <button class="btn danger" :disabled="!running" @click="job && jobs.cancel(job.id)">
        <Icon name="stop" :size="13" />
        {{ $t('pipeline.detail.cancelJob') }}
      </button>
    </div>

    <div class="body grid2">
      <div class="col">
        <div v-if="!job" class="panel">
          <div class="empty">{{ $t('pipeline.detail.noJob') }}</div>
        </div>
        <template v-else>
          <div class="panel jobcard">
            <div class="titlerow">
              <WorkerAvatar :sha="who?.cover" :color="color" :size="38" />
              <div class="min-w-0">
                <div class="nm">
                  <b>{{ who?.name }}</b>
                  <span v-if="who?.jp" class="jp">{{ who.jp }}</span>
                  <span class="chip mono kind">{{ job.type }}</span>
                  <span v-if="!running" class="kv">
                    {{ $t('pipeline.detail.lastJob', { state: $t(`pipeline.state.${job.state}`) }) }}
                  </span>
                </div>
                <div class="kv mono">
                  {{ sub }} · {{ $t('pipeline.started', { time: startedAt }) }} · {{ elapsedText }}
                </div>
              </div>
              <div class="spacer" />
              <div class="bigc">
                <div class="big">
                  <span class="mine">{{ posts }}</span>
                  <span v-if="target !== null" class="of">&nbsp;/ {{ target }}</span>
                </div>
                <div class="kv">
                  <template v-if="target !== null">
                    {{ $t('pipeline.detail.postsThisRun', { left: Math.max(0, target - posts) }) }}
                  </template>
                  <template v-else>{{ $t('pipeline.detail.newThisRun') }}</template>
                </div>
              </div>
            </div>

            <div v-if="showSplit" class="split">
              <div class="sk" :style="{ flex: gated || 1 }">
                {{ $t('pipeline.detail.split', { skipped: gated }) }}
              </div>
              <div class="nw" :style="{ flex: Math.max(listed - gated, 1) }">
                {{ $t('pipeline.detail.splitNew', { n: listed - gated }) }}
              </div>
            </div>

            <div class="stages">
              <template v-for="(st, si) in stages" :key="st">
                <Icon v-if="si > 0" name="chevron-right" :size="12" class="chev" />
                <span class="sblock" :class="si < at ? 'done' : si === at ? 'act' : 'todo'">
                  <Icon v-if="si < at" name="check" :size="12" />
                  <i v-else class="sdot" />
                  {{ $t(`pipeline.stage.${st}`) }}
                </span>
              </template>
            </div>

            <div v-if="running">
              <div class="plbl">
                <span class="pl">
                  {{
                    job.total !== null
                      ? $t('pipeline.detail.progress', {
                          stage: job.stage ? $t(`pipeline.stage.${job.stage}`) : '',
                          done: job.done,
                          total: job.total,
                        })
                      : $t('pipeline.detail.progressOpen', {
                          stage: job.stage ? $t(`pipeline.stage.${job.stage}`) : '',
                          done: job.done,
                        })
                  }}
                </span>
              </div>
              <div class="pbar" :class="{ indet: pct === null }">
                <div :style="{ width: (pct ?? 30) + '%' }" />
              </div>
              <div class="under kv">
                <span class="ok">{{ $t('pipeline.detail.kept', { n: c.stored ?? c.downloaded ?? 0 }) }}</span>
                <span class="err">{{ $t('pipeline.detail.dropped', { n: c.rejected ?? 0 }) }}</span>
                <span v-if="eta" class="eta">{{ $t('pipeline.detail.eta', { t: eta }) }}</span>
                <span v-if="pct === null" class="eta">{{ $t('pipeline.detail.noDenominator') }}</span>
              </div>
            </div>

            <div class="ctrs">
              <div v-for="k in counters" :key="k.key">
                <b :class="k.n ? k.tone : ''">{{ k.n.toLocaleString() }}</b>
                <span>{{ $t(`pipeline.counter.${k.key}`) }}</span>
              </div>
            </div>
          </div>

          <div class="panel log">
            <div class="phead">
              <span class="ptitle">{{ $t('pipeline.detail.log') }}</span>
              <div class="spacer" />
              <label class="kv">
                <input v-model="follow" type="checkbox" />
                {{ $t('pipeline.detail.followTail') }}
              </label>
            </div>
            <div ref="logEl" class="lines mono">
              <div v-for="l in lines" :key="l.key" class="line">
                <span class="t">{{ clock(l.at) }}</span>
                <span class="s">{{ l.src }}</span>
                <span class="k" :class="l.kind">{{ l.kind }}</span>
                <span class="m">{{ l.message }}</span>
              </div>
              <div v-if="!lines.length" class="kv">{{ $t('pipeline.detail.noLog') }}</div>
            </div>
          </div>
        </template>
      </div>

      <div class="panel side">
        <RateBudget />
        <QueuedPanel />
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
.back {
  width: 27px;
  height: 27px;
  padding: 0;
  justify-content: center;
  flex: none;
}
.title {
  white-space: nowrap;
}
.jp {
  font-family: var(--font-jp);
  color: var(--mut);
  font-weight: 500;
  margin-left: 6px;
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
  color: var(--wc);
  border: 1px solid color-mix(in oklch, var(--wc) 45%, transparent);
  background: color-mix(in oklch, var(--wc) 10%, transparent);
  white-space: nowrap;
}
.pill .dot {
  width: 6px;
  height: 6px;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.grid2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 366px;
  gap: 14px;
  min-height: 0;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  min-height: 0;
}
.jobcard {
  padding: 15px 17px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.titlerow {
  display: flex;
  align-items: center;
  gap: 12px;
}
.nm {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.nm b {
  font-weight: 600;
  font-size: 15px;
}
.kind {
  height: 19px;
  font-size: 10.5px;
  color: var(--wc);
  border-color: var(--wc);
}
.bigc {
  text-align: right;
  flex: none;
}
.big {
  font: 600 20px var(--font);
  white-space: nowrap;
}
.big .mine {
  color: var(--wc);
}
.big .of {
  color: var(--dim);
  font-weight: 500;
}
.split {
  display: flex;
  height: 24px;
  font: 11px var(--font-mono);
  border: 1px solid var(--line-soft);
}
.split > div {
  display: flex;
  align-items: center;
  padding: 0 10px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.split .sk {
  color: var(--dim);
  background: var(--surf2);
}
.split .nw {
  color: var(--wc);
  background: color-mix(in oklch, var(--wc) 18%, transparent);
  justify-content: flex-end;
}
.stages {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.chev {
  color: var(--dim);
}
.sblock {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 14px;
  font-size: 12.5px;
  border: 1px solid var(--line-soft);
  color: var(--dim);
}
.sblock .sdot {
  width: 6px;
  height: 6px;
  border: 1px solid currentColor;
}
.sblock.done {
  color: var(--moss);
  border-color: color-mix(in oklch, var(--moss) 45%, transparent);
  background: color-mix(in oklch, var(--moss) 10%, transparent);
}
.sblock.act {
  color: var(--wc);
  border-color: var(--wc);
  background: color-mix(in oklch, var(--wc) 12%, transparent);
}
.sblock.act .sdot {
  background: currentColor;
}
.plbl {
  display: flex;
  font-size: 12.5px;
}
.pl {
  color: var(--mut);
}
.pbar {
  height: 4px;
  margin-top: 7px;
  background: var(--surf2);
  overflow: hidden;
}
.pbar div {
  height: 100%;
  background: var(--wc);
  box-shadow: 0 0 8px var(--wc);
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
.under {
  display: flex;
  gap: 14px;
  margin-top: 6px;
}
.eta {
  margin-left: auto;
}
.ctrs {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}
.ctrs div {
  display: flex;
  flex-direction: column;
}
.ctrs b {
  font: 600 22px var(--font);
}
.ctrs span {
  font: 10px var(--font-mono);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--dim);
}
.moss {
  color: var(--moss);
}
.cyan {
  color: var(--cyan);
}
.rose {
  color: var(--rose);
}
.log {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 260px;
}
.lines {
  flex: 1;
  overflow: auto;
  padding: 9px 13px;
  font-size: 11px;
}
.line {
  display: flex;
  gap: 11px;
  padding: 3px 0;
}
.line .t {
  color: var(--dim);
  flex: 0 0 60px;
}
.line .s {
  color: var(--dim);
  flex: 0 0 44px;
}
.line .k {
  flex: 0 0 64px;
  color: var(--dim);
  font-weight: 500;
}
.k.new,
.k.stored {
  color: var(--moss);
}
.k.dupe {
  color: var(--cyan);
}
.k.failed,
.k.error,
.k.warning,
.k.rejected {
  color: var(--rose);
}
.k.gone {
  color: oklch(0.62 0.1 300);
}
.line .m {
  color: var(--mut);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.side {
  align-self: start;
}
@media (max-width: 1100px) {
  .grid2 {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
