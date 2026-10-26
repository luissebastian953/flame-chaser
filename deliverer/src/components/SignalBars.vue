<script setup lang="ts">
/** Four bars, the lit ones in moss (ember when the line is degraded): the rail card and the modal's header share it. */
withDefaults(defineProps<{ bars?: number; tone?: 'moss' | 'ember' }>(), { bars: 0, tone: 'moss' });
const HEIGHTS = [5, 8, 11, 14];
</script>

<template>
  <span class="bars" :class="tone" aria-hidden="true">
    <i v-for="(h, i) in HEIGHTS" :key="i" :class="{ lit: i < bars }" :style="{ height: h + 'px' }" />
  </span>
</template>

<style scoped>
.bars {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  flex: none;
}
.bars i {
  display: block;
  width: 3px;
  background: oklch(0.32 0.024 265);
}
.bars i.lit {
  background: var(--moss);
}
.bars.ember i.lit {
  background: var(--ember);
}
</style>
