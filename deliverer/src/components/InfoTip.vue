<script setup lang="ts">
/**
 * A small (i) that explains a setting in plain words. Reka's Tooltip for the
 * behaviour (opens on hover and on keyboard focus, Esc closes, aria wiring);
 * the look is ours. Portalled to <body> so it is never clipped by a modal.
 */
defineProps<{ label: string }>();
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <TooltipRoot>
      <TooltipTrigger class="info" :aria-label="label" type="button">
        <Icon name="info" :size="15" />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent class="rk-tooltip" side="top" :side-offset="6" :collision-padding="10">
          <slot />
          <TooltipArrow class="rk-tooltip-arrow" :width="10" :height="5" />
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>

<style scoped>
.info {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--dim);
  cursor: help;
  vertical-align: middle;
}
.info:hover,
.info:focus-visible,
.info[data-state='delayed-open'],
.info[data-state='instant-open'] {
  color: var(--ember);
  outline: none;
}
</style>
