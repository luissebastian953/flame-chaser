<script setup lang="ts">
/**
 * The rate budgets every worker shares, with what each actually sent in the
 * last minute (coreflame/http.py METER). The bar is that minute against the
 * budget's ceiling; gallery-dl paces itself, so it shows its calls instead.
 */
const jobs = useJobs();
const budgets = computed(() => jobs.pipeline?.budgets ?? []);

function fill(rate: number | null, perMin: number): number {
  if (rate === null) return perMin > 0 ? 100 : 0;
  return Math.min(100, Math.round((100 * perMin) / (rate * 60)));
}
</script>

<template>
  <div class="phead">
    <span class="ptitle">{{ $t('pipeline.budget.title') }}</span>
    <div class="spacer" />
    <span class="kv">{{ $t('pipeline.budget.hint') }}</span>
  </div>
  <div class="budgets">
    <div v-for="b in budgets" :key="b.key" class="bud">
      <div class="row">
        <span class="lbl">{{ b.label }}</span>
        <span class="num val">
          <template v-if="b.rate !== null">{{ $t('pipeline.budget.perSec', { n: b.rate }) }}</template>
          <template v-else-if="b.per_min">{{ $t('pipeline.budget.perMin', { n: b.per_min }) }}</template>
          <template v-else>{{ $t('pipeline.budget.idle') }}</template>
        </span>
      </div>
      <div class="track"><div :style="{ width: fill(b.rate, b.per_min) + '%' }" /></div>
    </div>
  </div>
</template>

<style scoped>
.budgets {
  padding: 6px 13px 12px;
}
.bud {
  padding: 7px 0;
}
.row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}
.lbl {
  color: var(--mut);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.val {
  margin-left: auto;
  flex: none;
}
.track {
  height: 3px;
  margin-top: 5px;
  background: var(--surf2);
}
.track div {
  height: 100%;
  background: var(--ember);
  transition: width 0.4s;
}
</style>
