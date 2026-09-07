<script setup lang="ts">
/** Rail banner above Shutdown. Cyan = something to do; quiet when nothing is. */
const up = useUpdater();
</script>

<template>
  <div v-if="up.phase === 'available'" class="ub">
    <div class="row">
      <span class="ic">⤓</span>
      <div class="flex-1 min-w-0">
        <div class="t">{{ $t('updates.banner.new') }}</div>
        <div class="data text-small text-dim">
          {{ up.version }}
          <span v-if="up.mb">· {{ up.mb }} MB</span>
        </div>
      </div>
      <button class="btn cy sm" @click="up.download()">{{ $t('updates.banner.update') }}</button>
    </div>
  </div>

  <div v-else-if="up.phase === 'downloading'" class="ub">
    <div class="row">
      <div class="t">{{ $t('updates.banner.updatingTo', { version: up.version }) }}</div>
      <div class="spacer" />
      <span class="data pct">{{ up.progress }}%</span>
    </div>
    <div class="bar"><div :style="{ width: up.progress + '%' }" /></div>
    <div class="data text-small text-dim">{{ $t('updates.banner.background') }}</div>
  </div>

  <div v-else-if="up.phase === 'ready' || up.phase === 'waiting' || up.phase === 'installing'" class="ub">
    <div class="row">
      <div class="flex-1 min-w-0">
        <div class="t">
          {{
            up.phase === 'installing'
              ? $t('updates.banner.restarting')
              : $t('updates.banner.ready', { version: up.version })
          }}
        </div>
        <div class="data text-small text-dim">
          {{ up.phase === 'waiting' ? $t('updates.banner.waiting') : $t('updates.banner.restartToFinish') }}
        </div>
      </div>
      <button v-if="up.phase === 'ready'" class="btn cy sm" @click="up.install()">
        {{ $t('updates.banner.restart') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ub {
  border: 1px solid color-mix(in oklch, var(--cyan) 45%, transparent);
  background: color-mix(in oklch, var(--cyan) 7%, var(--bg));
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.t {
  font-size: 14px;
  font-weight: 600;
}
.ic {
  color: var(--cyan);
  font-size: 16px;
}
.pct {
  color: var(--cyan);
  font-size: 13px;
}
.bar {
  height: 4px;
  background: var(--line-soft);
}
.bar > div {
  height: 100%;
  background: linear-gradient(90deg, var(--cyan), var(--ember));
  transition: width 0.3s;
}
.btn.cy {
  background: var(--cyan);
  border-color: var(--cyan);
  color: var(--ember-ink);
  font-weight: 600;
}
</style>
