<script setup lang="ts">
import type { Job, Lane } from '@/lib/types';
import type { Toast } from '@/stores/toasts';

/**
 * One "run started" toast. Everything it says is read live off the jobs
 * store: a character queued behind a busy worker, crawling with its stage
 * word, both sources side by side, held by a paused queue (amber, sticky),
 * or the error that stopped it (rose, sticky). Open pipeline goes to the
 * worker when one source ran, to the list when two did.
 */
const props = defineProps<{ toast: Toast }>();
const toasts = useToasts();
const jobs = useJobs();
const router = useRouter();
const { t, te, locale } = useI18n();

const SOURCE_NAME: Record<Lane, string> = {
  pixiv: 'crawl.table.sourcePixiv',
  twitter: 'crawl.table.sourceX',
};

const TITLE = { queued: 'crawl.toast.queued', running: 'crawl.toast.running', multi: 'crawl.toast.multi' };

const sourceName = (lane: Lane) => t(SOURCE_NAME[lane]);

/** the crawl jobs this toast follows, one per source, in lane order */
const mine = computed<Job[]>(() => {
  if (props.toast.kind !== 'run') return [];
  const ids = props.toast.jobIds;
  return jobs.jobs
    .filter((j) => ids.includes(j.id))
    .sort((a, b) => jobs.lanes.indexOf(laneOf(a)) - jobs.lanes.indexOf(laneOf(b)));
});

function laneOf(j: Job): Lane {
  return sourceOf(j) ?? j.worker ?? 'pixiv';
}

/** queued jobs this one waits behind on its lane, plus the one its worker is busy with */
function ahead(j: Job): number {
  const lane = laneOf(j);
  const queue = jobs.queued.filter((q) => laneOf(q) === lane);

  const before = Math.max(
    0,
    queue.findIndex((q) => q.id === j.id),
  );

  const busy = jobs.slots.find((s) => s.lane === lane)?.job;
  return before + (busy && busy.id !== j.id ? 1 : 0);
}

/** 1-based place in the whole queue */
const position = (j: Job) =>
  Math.max(
    0,
    jobs.queued.findIndex((q) => q.id === j.id),
  ) + 1;

const stageWord = (j: Job) => {
  const s = j.stage ?? stagesOf(j)[0] ?? '';
  return te(`pipeline.stage.${s}`) ? t(`pipeline.stage.${s}`) : s;
};

const stateWord = (j: Job) =>
  j.state === 'queued'
    ? t('crawl.toast.chipQueued', { n: ahead(j) })
    : j.state === 'running'
      ? stageWord(j)
      : t(`pipeline.state.${j.state}`);

const allQueued = computed(() => mine.value.length > 0 && mine.value.every((j) => j.state === 'queued'));
const paused = computed(() => props.toast.kind === 'run' && allQueued.value && !!jobs.pipeline?.paused);
const tone = computed(() => (props.toast.kind === 'error' ? 'err' : paused.value ? 'warn' : 'ok'));
const sticky = computed(() => tone.value !== 'ok');

const single = computed(() => (mine.value.length === 1 ? mine.value[0]! : null));

/** before the job list caught up (or with one source and nothing to follow) the toast reads as queued */
const lone = computed(() => mine.value.length === 0 && props.toast.sources.length <= 1);
const loneLane = computed<Lane>(() => props.toast.sources[0] ?? 'pixiv');
const sourceCount = computed(() => mine.value.length || props.toast.sources.length);

const title = computed(() =>
  single.value
    ? single.value.state === 'running'
      ? TITLE.running
      : TITLE.queued
    : lone.value
      ? TITLE.queued
      : TITLE.multi,
);

const dotColor = (j: Job) =>
  j.state === 'running' ? workerColor(workerIndex(j.worker ?? laneOf(j), jobs.lanes)) : 'var(--dim)';

/** the error's second line: where it happened, or what the daemon said */
const errorSub = computed(() => {
  const e = props.toast;
  if (e.kind !== 'error') return '';
  if (e.code !== 'nothing_to_run') return e.message;
  const where = e.sources.length ? e.sources.map(sourceName).join(' · ') : t('crawl.toast.noSources');
  const sub = t('crawl.toast.noMatchSub', { label: e.label, sources: where });
  return e.sources.includes('twitter') ? `${sub} · ${t('crawl.toast.terms', { n: e.terms }, e.terms)}` : sub;
});

// a sticky toast has no countdown; one that stops being sticky (queue resumed) starts its own
watch(
  sticky,
  (s) => {
    if (s) toasts.hold(props.toast.id);
    else toasts.arm(props.toast.id);
  },
  { immediate: true },
);

function open() {
  const lane = single.value ? laneOf(single.value) : lone.value ? loneLane.value : null;
  const target = lane ? `/pipeline/${lane}` : '/pipeline';
  toasts.dismiss(props.toast.id);
  router.push(target);
}

async function retry() {
  const again = props.toast.retry;
  toasts.dismiss(props.toast.id);
  await again();
}
</script>

<template>
  <div class="toast" :class="[tone, { jp: locale === 'ja', held: toasts.held }]" role="status">
    <div class="row">
      <template v-if="toast.kind === 'error'">
        <div class="ttl">
          {{
            toast.code === 'nothing_to_run'
              ? $t('crawl.toast.noMatch')
              : toast.code === 'unreachable'
                ? $t('crawl.toast.unreachable')
                : $t('crawl.toast.failed')
          }}
        </div>
      </template>
      <div v-else-if="paused" class="ttl">{{ $t('crawl.toast.paused', { label: toast.label }) }}</div>
      <i18n-t v-else v-bind="{ keypath: title }" tag="div" class="ttl">
        <template #label>{{ toast.label }}</template>
        <template #source>
          <em>{{ sourceName(single ? laneOf(single) : loneLane) }}</em>
        </template>
        <template #n>{{ sourceCount }}</template>
      </i18n-t>
      <button class="x" :aria-label="$t('crawl.toast.close')" @click="toasts.dismiss(toast.id)">
        <Icon name="close" :size="12" />
      </button>
    </div>

    <div class="foot">
      <div v-if="toast.kind === 'error'" class="sub">{{ errorSub }}</div>
      <div v-else-if="single && paused" class="sub">
        {{ $t('crawl.toast.position', { source: sourceName(laneOf(single)), n: position(single) }) }}
      </div>
      <div v-else-if="single && single.state === 'queued'" class="sub">
        {{ $t('crawl.toast.behind', { n: ahead(single) }, ahead(single)) }}
      </div>
      <div v-else-if="single" class="sub">
        <Transition name="stage" mode="out-in">
          <span :key="stateWord(single)" class="stage">{{ stateWord(single) }}</span>
        </Transition>
      </div>
      <div v-else-if="lone" class="sub">{{ $t('crawl.toast.behind', { n: 0 }, 0) }}</div>
      <template v-else>
        <span v-for="j in mine" :key="j.id" class="src">
          <span class="d" :class="{ lit: j.state === 'running' }" :style="{ background: dotColor(j) }" />
          {{ sourceName(laneOf(j)) }}
          <b>
            <Transition name="stage" mode="out-in">
              <span :key="stateWord(j)">{{ stateWord(j) }}</span>
            </Transition>
          </b>
        </span>
      </template>
      <div class="spacer" />
      <button v-if="toast.kind === 'error'" class="act" @click="retry">{{ $t('crawl.toast.retry') }}</button>
      <button v-else-if="paused" class="act" @click="jobs.pauseQueue(false)">
        {{ $t('crawl.toast.resume') }}
      </button>
      <button v-else class="act" @click="open">{{ $t('crawl.toast.open') }}</button>
    </div>

    <div v-if="!sticky" class="timer" aria-hidden="true"><i /></div>
  </div>
</template>

<style scoped>
.toast {
  --tone: var(--color-ember);
  --cut: 10px;
  position: relative;
  width: 360px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px 14px 13px 16px;
  background: color-mix(in oklch, var(--color-surf) 82%, transparent);
  -webkit-backdrop-filter: blur(12px) saturate(1.2);
  backdrop-filter: blur(12px) saturate(1.2);
  border: 1px solid var(--color-line);
  color: var(--color-tx);
  overflow: hidden;
  /* clip-path clips box-shadow, so the lift and the tone glow are drop-shadows */
  filter: drop-shadow(0 8px 24px oklch(0 0 0 / 0.25))
    drop-shadow(0 0 10px color-mix(in oklch, var(--tone) 22%, transparent));
}
.toast.warn {
  --tone: oklch(0.8 0.15 75);
}
.toast.err {
  --tone: var(--color-rose);
}
/* the tone tick on the left edge */
.toast::before {
  content: '';
  position: absolute;
  left: 0;
  top: 13px;
  width: 3px;
  height: 14px;
  background: var(--tone);
  box-shadow: 0 0 8px var(--tone);
}
:global(.corners-cut) .toast {
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
:global(.corners-round) .toast {
  border-radius: 8px;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.ttl {
  flex: 1;
  min-width: 0;
  padding-right: 4px;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.3;
}
.ttl em {
  font-style: normal;
  color: var(--tone);
}
.x {
  flex: none;
  width: 24px;
  height: 24px;
  margin: -5px -6px 0 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  padding: 0;
  color: var(--color-dim);
}
.x:hover {
  color: var(--color-tx);
}

.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sub {
  display: flex;
  align-items: center;
  gap: 7px;
  font: 11px/1.3 var(--font-mono);
  color: var(--color-dim);
}
.sub .stage {
  display: inline-block;
  color: var(--tone);
}
.act {
  --cut: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 25px;
  padding: 0 10px;
  border: 1px solid var(--tone);
  background: transparent;
  color: var(--tone);
  font: 600 10.5px var(--font-sans);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  white-space: nowrap;
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.act:hover {
  background: color-mix(in oklch, var(--tone) 14%, transparent);
}
:global(.corners-round) .act {
  clip-path: none;
  border-radius: 4px;
}
.toast.jp .act {
  font-family: var(--font-jp);
  font-size: 11px;
  letter-spacing: 0.02em;
  text-transform: none;
}

/* one chip per source when both ran */
.src {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--color-line);
  background: var(--color-surf2);
  font-size: 11px;
  color: var(--color-tx);
}
.src b {
  font: 500 10.5px var(--font-mono);
  color: var(--color-dim);
}
.src .d {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.src .d.lit {
  box-shadow: 0 0 6px currentColor;
  color: inherit;
}

/* the countdown, drained over the toast's life; held while the pointer is on the stack */
.timer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--color-line-soft);
}
.timer i {
  display: block;
  height: 100%;
  width: 100%;
  background: var(--tone);
  transform-origin: left;
  animation: drain 6s linear forwards;
}
.toast.held .timer i {
  animation-play-state: paused;
}
@keyframes drain {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

/* the stage word swaps with a short lift */
.stage-enter-active,
.stage-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms ease;
}
.stage-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.stage-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .timer i {
    animation: none;
  }
  .stage-enter-active,
  .stage-leave-active {
    transition: none;
  }
}
</style>
