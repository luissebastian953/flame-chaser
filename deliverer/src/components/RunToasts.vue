<script setup lang="ts">
/**
 * The toast stack: bottom-right of the content area (never over the rail),
 * newest at the bottom, up to three. Hovering any toast holds every
 * countdown; Esc dismisses the newest one.
 */
const toasts = useToasts();

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !toasts.items.length) return;
  toasts.dismiss(toasts.items[toasts.items.length - 1]!.id);
}

onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));
</script>

<template>
  <div class="toasts" @mouseenter="toasts.pauseTimers()" @mouseleave="toasts.resumeTimers()">
    <TransitionGroup name="toast">
      <RunToast v-for="toast in toasts.items" :key="toast.id" :toast="toast" />
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  max-width: calc(100% - 32px);
  pointer-events: none;
}
.toasts > * {
  pointer-events: auto;
}

/* rise in, sink out; the stack above shifts with it */
.toast-enter-active,
.toast-leave-active,
.toast-move {
  transition:
    transform 350ms cubic-bezier(0.2, 0.7, 0.2, 1),
    opacity 350ms ease;
}
.toast-leave-active {
  position: absolute;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(12px);
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active,
  .toast-move {
    transition: none;
  }
}
</style>
