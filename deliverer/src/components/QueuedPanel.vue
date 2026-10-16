<script setup lang="ts">
/**
 * The queue in the order the workers will take it. Drag a row to reorder;
 * "Run now" moves a job to the front (it starts as soon as its worker is
 * free -- a running job is never pre-empted).
 */
import type { Job } from '@/lib/types';

const jobs = useJobs();
const lib = useLibrary();
const { t } = useI18n();

const dragging = ref<string | null>(null);

function title(j: Job): string {
  const ch = characterOf(j, lib.watches);
  if (ch) return `${ch.name} · ${t(`pipeline.lane.${sourceOf(j) ?? 'pixiv'}`)}`;
  const tt = jobTitle(j);
  return t(tt.key, tt.params);
}

function meta(j: Job): string {
  const m = queueMeta(j, lib.watches);
  return m ? t(m.key, m.n) : '';
}

function drop(target: string) {
  const from = dragging.value;
  dragging.value = null;
  if (!from || from === target) return;
  const ids = jobs.queued.map((j) => j.id).filter((id) => id !== from);
  ids.splice(ids.indexOf(target), 0, from);
  jobs.reorder(ids).catch(() => {});
}
</script>

<template>
  <div class="phead">
    <span class="ptitle">{{ $t('pipeline.queued') }}</span>
    <div class="spacer" />
    <span class="kv">{{ $t('pipeline.queuedHint') }}</span>
  </div>
  <div v-if="jobs.queued.length" class="rows">
    <div
      v-for="(j, i) in jobs.queued"
      :key="j.id"
      class="qrow"
      :class="{ drag: dragging === j.id }"
      draggable="true"
      @dragstart="dragging = j.id"
      @dragend="dragging = null"
      @dragover.prevent
      @drop.prevent="drop(j.id)"
    >
      <span class="mono idx">{{ i + 1 }}</span>
      <span class="chip mono kind">{{ j.type }}</span>
      <span class="lbl">{{ title(j) }}</span>
      <span class="num meta">{{ meta(j) }}</span>
      <button class="btn gh sm xs" @click="jobs.runNow(j.id)">{{ $t('pipeline.runNow') }}</button>
      <button
        class="btn gh sm xs"
        :title="$t('pipeline.cancel')"
        :aria-label="$t('pipeline.cancel')"
        @click="jobs.cancel(j.id)"
      >
        <Icon name="close" :size="12" />
      </button>
    </div>
  </div>
  <div v-else class="kv empty-q">{{ $t('pipeline.queueEmpty') }}</div>
</template>

<style scoped>
.qrow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 13px;
  border-bottom: 1px solid var(--line-soft);
  cursor: grab;
}
.qrow:last-child {
  border-bottom: none;
}
.qrow.drag {
  opacity: 0.45;
}
.idx {
  flex: 0 0 14px;
  font-size: 10px;
  color: var(--dim);
}
.kind {
  flex: none;
  height: 19px;
  font-size: 10.5px;
}
.lbl {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
}
.meta {
  flex: none;
  text-align: right;
}
.xs {
  height: 21px;
  flex: none;
}
.empty-q {
  padding: 12px 13px;
}
</style>
