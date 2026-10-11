<script setup lang="ts">
/**
 * One icon of the Curio set (lib/icons.ts). Decorative by default (hidden
 * from screen readers, next to text that says the same); pass `label` when
 * the icon is the only thing that names a control.
 */
const props = withDefaults(defineProps<{ name: string; size?: number; label?: string }>(), { size: 16 });

const paths = computed(() => ICON_PATHS.get(props.name) ?? []);

if (import.meta.env.DEV) {
  watchEffect(() => {
    if (!ICON_PATHS.has(props.name)) console.warn(`<Icon>: no icon named "${props.name}"`);
  });
}
</script>

<template>
  <svg
    class="icon"
    viewBox="0 0 24 24"
    :width="size"
    :height="size"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="square"
    stroke-linejoin="miter"
    focusable="false"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" />
  </svg>
</template>

<style scoped>
.icon {
  display: inline-block;
  flex: 0 0 auto;
  vertical-align: -0.2em;
}
</style>
