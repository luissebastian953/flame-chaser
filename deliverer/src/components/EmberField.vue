<script setup lang="ts">
/**
 * Embers drifting up behind the pipeline while a worker runs -- decoration
 * only (aria-hidden, no pointer events). Still under prefers-reduced-motion.
 */
const EMBERS = Array.from({ length: 22 }, (_, i) => ({
  left: `${(i * 37) % 100}%`,
  delay: `${-((i * 1.7) % 12)}s`,
  duration: `${9 + ((i * 3) % 7)}s`,
  size: `${2 + (i % 3)}px`,
}));
</script>

<template>
  <div class="embers" aria-hidden="true">
    <span
      v-for="(e, i) in EMBERS"
      :key="i"
      :style="{
        left: e.left,
        animationDelay: e.delay,
        animationDuration: e.duration,
        width: e.size,
        height: e.size,
      }"
    />
  </div>
</template>

<style scoped>
.embers {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}
.embers span {
  position: absolute;
  bottom: -10px;
  background: var(--ember);
  box-shadow: 0 0 6px var(--ember);
  opacity: 0;
  animation: rise linear infinite;
}
@keyframes rise {
  0% {
    transform: translate(0, 0);
    opacity: 0;
  }
  10% {
    opacity: 0.55;
  }
  100% {
    transform: translate(24px, -105vh);
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .embers span {
    animation: none;
    opacity: 0.25;
    bottom: auto;
    top: 50%;
  }
}
</style>
