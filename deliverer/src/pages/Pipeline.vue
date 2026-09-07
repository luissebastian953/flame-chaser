<script setup lang="ts">
const jobs = useJobs();
const logEl = ref<HTMLElement | null>(null);
const follow = ref(true);

onMounted(() => jobs.load());

const running = computed(() => jobs.running);

const pct = computed(() => {
  const j = running.value;
  if (!j || j.total === null || j.total === 0) return null;
  return Math.min(100, Math.round((100 * j.done) / j.total));
});

const lines = computed(() =>
  jobs.events.filter((e) => e.type !== 'job.progress' && e.type !== 'rate.budget'),
);

watch(lines, async () => {
  if (follow.value) {
    await nextTick();
    logEl.value?.scrollTo(0, logEl.value.scrollHeight);
  }
});

function short(s: string | null | undefined) {
  return (s ?? '').slice(11, 19);
}
</script>

<template>
  <div class="top">
    <div>
      <div class="h1">{{ $t('pipeline.title') }}</div>
      <div class="sub">
        {{
          $t('pipeline.sub', {
            status: running ? $t('pipeline.oneRunning') : $t('pipeline.idle'),
            queued: $t('pipeline.queuedCount', jobs.queued.length),
          })
        }}
      </div>
    </div>
    <div class="spacer" />
    <button
      class="btn"
      :disabled="!running"
      style="border-color: oklch(0.42 0.08 18); color: var(--rose)"
      @click="running && jobs.cancel(running.id)"
    >
      {{ $t('pipeline.cancelJob') }}
    </button>
  </div>
  <div class="body grid">
    <div v-if="running" class="panel job">
      <div class="row">
        <span class="chip" style="border-color: var(--ember); color: var(--ember)">{{ running.type }}</span>
        <b>{{ $t('pipeline.stage', { stage: running.stage ?? '—' }) }}</b>
        <span class="kv">{{ $t('pipeline.started', { time: short(running.started_at) }) }}</span>
        <div class="spacer" />
        <span class="num">
          {{ $t('pipeline.counter', { done: running.done, total: running.total ?? '?' }) }}
        </span>
      </div>
      <div class="bar" :class="{ indet: pct === null }"><div :style="{ width: (pct ?? 30) + '%' }" /></div>
      <div v-if="pct === null" class="kv">
        {{ $t('pipeline.noDenominator') }}
      </div>
    </div>
    <div v-else class="panel job">
      <div class="empty">{{ $t('pipeline.noJob') }}</div>
    </div>

    <div class="panel side">
      <div class="phead">
        <span class="ptitle">{{ $t('pipeline.queued') }}</span>
      </div>
      <table v-if="jobs.queued.length">
        <tbody>
          <tr v-for="j in jobs.queued" :key="j.id">
            <td>
              <span class="chip mono">{{ j.type }}</span>
            </td>
            <td class="kv mono">{{ j.id }}</td>
            <td style="text-align: right">
              <button
                class="btn gh sm"
                :title="$t('pipeline.cancel')"
                :aria-label="$t('pipeline.cancel')"
                @click="jobs.cancel(j.id)"
              >
                ✕
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="kv" style="padding: 12px">{{ $t('pipeline.empty') }}</div>
      <div class="phead">
        <span class="ptitle">{{ $t('pipeline.recent') }}</span>
      </div>
      <table>
        <tbody>
          <tr v-for="j in jobs.recent" :key="j.id">
            <td>
              <span class="chip mono">{{ j.type }}</span>
            </td>
            <td :class="{ err: j.state === 'failed' }">{{ $t(`pipeline.state.${j.state}`) }}</td>
            <td class="num">{{ short(j.finished_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel log">
      <div class="phead">
        <span class="ptitle">{{ $t('pipeline.log') }}</span>
        <div class="spacer" />
        <label class="kv">
          <input v-model="follow" type="checkbox" />
          {{ $t('pipeline.followTail') }}
        </label>
      </div>
      <div ref="logEl" class="lines mono">
        <div v-for="e in lines" :key="e.id" class="line">
          <span class="t">{{ short(String(e.data.at ?? '')) }}</span>
          <span class="k" :class="String(e.data.action ?? e.data.level ?? e.type.split('.')[1])">
            {{ e.data.action ?? e.data.level ?? e.type.split('.')[1] }}
          </span>
          <span class="m">{{ e.data.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  grid-template-rows: auto 1fr;
  gap: 14px;
  overflow: hidden;
}
.job {
  grid-column: 1;
  padding: 15px 17px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.side {
  grid-column: 2;
  grid-row: 1 / span 2;
  overflow: auto;
}
.log {
  grid-column: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.row {
  display: flex;
  align-items: center;
  gap: 11px;
}
.bar {
  height: 4px;
  border-radius: 0;
  background: var(--surf2);
  overflow: hidden;
}
.bar div {
  height: 100%;
  background: var(--ember);
  transition: width 0.3s;
}
.bar.indet div {
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
.t {
  color: var(--dim);
  flex: 0 0 60px;
}
.k {
  flex: 0 0 60px;
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
.k.warning {
  color: var(--rose);
}
.k.gone {
  color: oklch(0.62 0.1 300);
}
.m {
  color: var(--mut);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
