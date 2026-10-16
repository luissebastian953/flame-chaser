<script setup lang="ts">
/**
 * A status card (Crawl's four, the pipeline's workers). `decoratedBorder`
 * adds the two corner marks -- an ember right angle floating off the
 * top-right and bottom-left corners. They sit on a wrapper because `.panel`
 * clips its box (overflow hidden, optional cut corners).
 */
defineProps<{ decoratedBorder?: boolean }>();
</script>

<template>
  <div class="statcard" :class="{ decorated: decoratedBorder }">
    <div class="panel card">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.statcard {
  position: relative;
  min-width: 0;
  display: flex;
}
.card {
  flex: 1;
  min-width: 0;
  padding: 13px 15px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 118px;
}
/* corner marks: a right angle of two 2px strokes, no fill, lifted 4px off
   the border; drop-shadow (not box-shadow) so the glow follows the L */
.decorated::before,
.decorated::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  pointer-events: none;
  border: 0 solid var(--color-ember);
  filter: drop-shadow(0 0 3px color-mix(in oklch, var(--color-ember) 70%, transparent));
}
.decorated::before {
  top: -4px;
  right: -4px;
  border-top-width: 2px;
  border-right-width: 2px;
}
.decorated::after {
  bottom: -4px;
  left: -4px;
  border-bottom-width: 2px;
  border-left-width: 2px;
}
</style>
