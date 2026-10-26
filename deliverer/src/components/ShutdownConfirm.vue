<script setup lang="ts">
import { characterOf, postsOf, sourceOf, targetOf } from '@/lib/pipeline';

/**
 * The rail's Shutdown button asks first. The box in the middle says what the
 * daemon is doing right now: each running crawl with its character, source
 * and progress, and how many jobs wait in the queue -- or one line that
 * nothing runs. "No" has focus, so Enter does nothing until Tab reaches
 * "Yes"; Esc is No. A crawl cut mid-run is marked interrupted on the next
 * launch (coreflame/jobs.py); queued jobs stay queued.
 */
const emit = defineEmits<{ close: []; confirm: [] }>();
const jobs = useJobs();
const lib = useLibrary();
const { t, te } = useI18n();

const no = ref<HTMLButtonElement | null>(null);

function srcLabel(s: string | null) {
  const key = `gallery.aside.source.${s ?? ''}`;
  return s && te(key) ? t(key) : (s ?? '');
}

/** "Ganyu · pixiv · 184 / 300 posts" for one running job */
function describe(job: (typeof jobs.running)[number]): string {
  const parts: string[] = [];
  const who = characterOf(job, lib.watches);
  if (who) parts.push(who.name);
  const src = srcLabel(sourceOf(job));
  if (src) parts.push(src);
  const target = targetOf(job);
  if (target) parts.push(t('app.shutdown.progress', { done: postsOf(job), total: target }));
  else if (job.total) parts.push(t('app.shutdown.progress', { done: job.done, total: job.total }));
  else if (job.stage) parts.push(job.stage);
  return parts.join(' · ');
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    emit('close');
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey, true);
  no.value?.focus();
});

onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <div class="scrim" @click="emit('close')" />
  <div class="modal panel" role="alertdialog" aria-modal="true" :aria-label="$t('app.shutdown.title')">
    <div class="head">
      <span class="pw"><Icon name="power" :size="14" /></span>
      <span class="ttl">{{ $t('app.shutdown.title') }}</span>
    </div>
    <div class="body">
      <p class="lead">{{ $t('app.shutdown.body') }}</p>
      <ul class="status">
        <template v-if="jobs.running.length || jobs.queued.length">
          <li v-for="job in jobs.running" :key="job.id" class="run">
            <i class="dot ember" aria-hidden="true" />
            <span>
              <b>{{ $t('app.shutdown.running', { n: jobs.running.length }, jobs.running.length) }}</b>
              <template v-if="describe(job)">· {{ describe(job) }}</template>
              <em>{{ $t('app.shutdown.runningNote') }}</em>
            </span>
          </li>
          <li v-if="jobs.queued.length">
            <i class="dot" aria-hidden="true" />
            <span>
              <b>{{ $t('app.shutdown.queued', { n: jobs.queued.length }, jobs.queued.length) }}</b>
              <em>{{ $t('app.shutdown.queuedNote') }}</em>
            </span>
          </li>
        </template>
        <li v-else>
          <i class="dot moss" aria-hidden="true" />
          <span>{{ $t('app.shutdown.none') }}</span>
        </li>
      </ul>
    </div>
    <div class="foot">
      <span class="kv mono">{{ $t('app.shutdown.hint') }}</span>
      <div class="spacer" />
      <button ref="no" class="btn gh" @click="emit('close')">{{ $t('app.shutdown.no') }}</button>
      <button class="btn danger yes" @click="emit('confirm')">
        <Icon name="power" :size="13" />
        {{ $t('app.shutdown.yes') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: oklch(0 0 0 / 0.6);
  backdrop-filter: blur(2px);
}
.modal {
  position: fixed;
  z-index: 41;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: min(560px, 92vw);
  border-color: color-mix(in oklch, var(--rose) 55%, var(--line));
  display: flex;
  flex-direction: column;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 22px;
  border-bottom: 1px solid var(--line-soft);
}
.pw {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--rose);
  color: var(--rose);
}
.ttl {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.body {
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.lead {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--mut);
}
.status {
  margin: 0;
  padding: 12px 14px;
  list-style: none;
  border: 1px solid var(--line-soft);
  background: var(--bg);
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: var(--mut);
}
.status li {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.status b {
  color: var(--tx);
  font-weight: 600;
}
.status em {
  font-style: normal;
  color: var(--dim);
  margin-left: 6px;
}
.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--dim);
  transform: translateY(-1px);
}
.dot.ember {
  background: var(--ember);
  box-shadow: 0 0 8px color-mix(in oklch, var(--ember) 60%, transparent);
}
.dot.moss {
  background: var(--moss);
}
.foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 22px;
  border-top: 1px solid var(--line-soft);
}
.foot .btn {
  min-width: 120px;
  justify-content: center;
}
.yes {
  background: var(--rose);
  border-color: var(--rose);
  color: var(--color-ember-ink);
  font-weight: 600;
}
.yes:hover {
  background: color-mix(in oklch, var(--rose) 85%, white);
}
</style>
