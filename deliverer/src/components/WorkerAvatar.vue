<script setup lang="ts">
/**
 * A character's cover thumbnail, ringed and lit in its worker's colour. With
 * no cover (a job that is not about one character, or nothing stored yet) a
 * gradient tile in the same colour stands in.
 */
const props = withDefaults(
  defineProps<{ sha?: string | null; color?: string | null; size?: number; ring?: boolean }>(),
  { sha: null, color: null, size: 40, ring: true },
);

const src = computed(() => (props.sha ? mediaUrl(props.sha) : null));
const tint = computed(() => props.color ?? 'var(--line)');

const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  '--tint': tint.value,
}));
</script>

<template>
  <span class="av" :class="{ ring }" :style="style">
    <img v-if="src" :src="src" alt="" loading="lazy" />
    <span v-else class="ph" />
  </span>
</template>

<style scoped>
.av {
  position: relative;
  flex: none;
  display: inline-block;
  overflow: hidden;
  background: var(--surf2);
}
.av.ring {
  box-shadow:
    0 0 0 1px var(--tint),
    0 0 12px color-mix(in oklch, var(--tint) 42%, transparent);
}
.av img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ph {
  position: absolute;
  inset: 0;
  background:
    repeating-linear-gradient(to bottom, transparent 0 2px, oklch(1 0 0 / 0.05) 2px 3px),
    linear-gradient(140deg, color-mix(in oklch, var(--tint) 55%, var(--surf2)), var(--surf2) 75%);
}
</style>
