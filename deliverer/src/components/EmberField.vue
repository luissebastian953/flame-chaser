<script setup lang="ts">
/**
 * Embers rising from a bright line glow at the bottom edge while a worker
 * runs. When `active` drops (paused, stopped) no ember launches again and
 * the whole field - line, haze and the embers already flying - fades out,
 * then empties itself so nothing keeps animating. Decoration only (aria-hidden, no pointer events). Embers hold full
 * glow to 50% of the container height and fade out by 80%. They stay still
 * under prefers-reduced-motion.
 *
 * Color comes from the parent's --ember (falls back to cyan).
 * Values are deterministic (no Math.random) so SSR and hydration match.
 */
const props = defineProps<{ active: boolean }>();

const COUNT = 96;

const EMBERS = Array.from({ length: COUNT }, (_, i) => {
  const far = i % 3 === 0; // every third ember sits further back
  const d = far ? 20 + ((i * 7) % 9) : 14 + ((i * 5) % 8); // seconds
  return {
    far,
    style: {
      '--x': `${(i * 61.803) % 100}%`,
      '--s': `${far ? 2 + (i % 2) : 2 + (i % 4)}px`,
      '--d': `${d}s`,
      '--delay': `${-((i * 2.3) % d).toFixed(1)}s`,
      '--drift': `${(i % 2 ? 1 : -1) * (10 + ((i * 13) % 45))}px`,
      '--rest': `${8 + ((i * 29) % 45)}cqh`,
    },
  };
});

/** how long a stopped field takes to fade out before its embers are removed */
const FADE_MS = 2500;

const root = ref<HTMLElement | null>(null);
/** the embers are in the DOM; false once a stopped field has burnt out */
const lit = ref(props.active);
let outTimer: ReturnType<typeof setTimeout> | undefined;

/** no ember starts another flight; one still on the line goes out now */
function stopLaunching() {
  for (const a of root.value?.getAnimations?.({ subtree: true }) ?? []) {
    if (!(a instanceof CSSAnimation) || a.animationName !== 'rise') continue;
    const { currentIteration, progress } = a.effect?.getComputedTiming() ?? {};
    if (currentIteration == null) continue;
    a.effect?.updateTiming({ iterations: currentIteration + ((progress ?? 0) < 0.04 ? 0 : 1) });
  }
}

watch(
  () => props.active,
  (on) => {
    clearTimeout(outTimer);
    if (on) {
      // a fresh field: the spans remount mid-flight from their negative delays
      lit.value = false;
      void nextTick(() => (lit.value = true));
      return;
    }
    stopLaunching();
    outTimer = setTimeout(() => (lit.value = false), FADE_MS);
  },
);

onBeforeUnmount(() => clearTimeout(outTimer));
</script>

<template>
  <div ref="root" class="embers" :class="{ out: !active }" aria-hidden="true">
    <div v-if="lit" class="flight">
      <span v-for="(e, i) in EMBERS" :key="i" class="p" :class="{ far: e.far }" :style="e.style" />
    </div>
  </div>
</template>

<style scoped>
.embers {
  --c: var(--ember, #3ff5ff);
  --c-hot: color-mix(in srgb, var(--c) 35%, #fff);
  --c-soft: color-mix(in srgb, var(--c) 55%, transparent);
  --c-faint: color-mix(in srgb, var(--c) 16%, transparent);

  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
  container-type: size; /* lets embers travel in cqh (container height), not vh */
}

/* Source line: thick, bright bottom edge with a white-hot core */
.embers::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 4px;
  background: linear-gradient(90deg, transparent, var(--c) 6%, var(--c-hot) 50%, var(--c) 94%, transparent);
  box-shadow:
    0 0 4px var(--c),
    0 -2px 10px var(--c-soft);
  animation: breathe 6s ease-in-out infinite;
  transition: opacity 1.2s ease-out;
  z-index: 1;
}

/* Line glow: haze rising off the edge */
.embers::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 32%;
  background: linear-gradient(
    to top,
    var(--c-faint) 0%,
    color-mix(in srgb, var(--c) 6%, transparent) 30%,
    transparent 100%
  );
  animation: breathe 9s ease-in-out infinite reverse;
  transition: opacity 1.6s ease-out;
}
/* stopped: the source dies down (the animation lets go so the fade can run) */
.embers.out::before,
.embers.out::after {
  animation: none;
  opacity: 0;
}

/* Embers: the wrapper fades them as one while each keeps its own keyframes */
.flight {
  position: absolute;
  inset: 0;
  transition: opacity 2.4s ease-out;
}
.embers.out .flight {
  opacity: 0;
}
.p {
  position: absolute;
  bottom: 2px; /* born on the line */
  left: var(--x);
  width: var(--s);
  height: var(--s);
  margin-left: calc(var(--s) / -2);
  border-radius: 50%;
  background: var(--c);
  box-shadow:
    0 0 calc(var(--s) * 2) var(--c),
    0 0 calc(var(--s) * 5) var(--c-soft);
  opacity: 0;
  will-change: transform, opacity;
  animation:
    rise var(--d) linear infinite,
    flicker calc(var(--d) / 5) ease-in-out infinite alternate;
  animation-delay: var(--delay), var(--delay);
  z-index: 2;
}
/* depth: far embers are dimmer and softer */
.p.far {
  --peak: 0.45;
  --blur: 1px;
}

@keyframes rise {
  /* linear travel 0 -> 80% of container, so 62.5% of the timeline = 50% */
  0% {
    transform: translate3d(0, 0, 0) scale(1);
    opacity: 0;
  }
  4% {
    opacity: var(--peak, 0.9);
  }
  62.5% {
    transform: translate3d(var(--drift), -50cqh, 0) scale(0.9);
    opacity: var(--peak, 0.9);
  }
  100% {
    transform: translate3d(calc(var(--drift) * 0.4), -80cqh, 0) scale(0.55);
    opacity: 0;
  }
}
/* blur is carried in the keyframes so far embers keep it while flickering */
@keyframes flicker {
  from {
    filter: blur(var(--blur, 0px)) brightness(1);
  }
  to {
    filter: blur(var(--blur, 0px)) brightness(1.6);
  }
}
@keyframes breathe {
  0%,
  100% {
    opacity: 0.75;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .embers::before,
  .embers::after,
  .p {
    animation: none;
  }
  .p {
    opacity: calc(var(--peak, 0.9) * 0.6);
    transform: translateY(calc(var(--rest) * -1));
  }
}
</style>
