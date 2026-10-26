<script setup lang="ts">
import type { DeleteToast } from '@/stores/toasts';

/**
 * "23 images moved to trash" - rose tick, the character, the size and how
 * many posts were forgotten, and Undo while it shows. Sticky ten seconds,
 * then it goes; Undo restores the batch from trash and un-forgets the posts.
 */
const props = defineProps<{ toast: DeleteToast }>();
const toasts = useToasts();
const fm = useFormats();
const { t, locale } = useI18n();
const undoing = ref(false);
const failed = ref('');

const sub = computed(() => {
  const base = t('gallery.delete.toast.sub', { label: props.toast.label, size: fm.bytes(props.toast.bytes) });
  const n = props.toast.forgotten;
  return n ? `${base} · ${t('gallery.delete.toast.forgotten', { n }, n)}` : base;
});

onMounted(() => toasts.arm(props.toast.id, DELETE_TTL));

async function undo() {
  if (undoing.value) return;
  undoing.value = true;
  toasts.hold(props.toast.id);
  try {
    await props.toast.undo();
    toasts.dismiss(props.toast.id);
  } catch (e) {
    failed.value = e instanceof Error ? e.message : String(e);
    undoing.value = false;
    toasts.arm(props.toast.id, DELETE_TTL);
  }
}
</script>

<template>
  <div class="toast" :class="{ jp: locale === 'ja' }" role="status">
    <div class="row">
      <div class="ttl">
        {{
          toast.permanent
            ? $t('gallery.delete.toast.deleted', { n: fm.number(toast.images) }, toast.images)
            : $t('gallery.delete.toast.trashed', { n: fm.number(toast.images) }, toast.images)
        }}
      </div>
      <button class="x" :aria-label="$t('gallery.delete.toast.close')" @click="toasts.dismiss(toast.id)">
        <Icon name="close" :size="12" />
      </button>
    </div>
    <div class="foot">
      <div class="sub">{{ failed || sub }}</div>
      <div class="spacer" />
      <button v-if="toast.batchId" class="act" :disabled="undoing" @click="undo">
        <Icon v-if="undoing" name="loader" class="spin" :size="11" />
        {{ $t('gallery.delete.toast.undo') }}
      </button>
    </div>
    <div class="timer" aria-hidden="true"><i /></div>
  </div>
</template>

<style scoped>
.toast {
  --tone: var(--color-rose);
  --cut: 10px;
  position: relative;
  width: 360px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px 14px 13px 16px;
  background: color-mix(in oklch, var(--color-surf) 82%, transparent);
  -webkit-backdrop-filter: blur(12px) saturate(1.2);
  backdrop-filter: blur(12px) saturate(1.2);
  border: 1px solid var(--color-line);
  color: var(--color-tx);
  overflow: hidden;
  filter: drop-shadow(0 8px 24px oklch(0 0 0 / 0.25))
    drop-shadow(0 0 10px color-mix(in oklch, var(--tone) 22%, transparent));
}
.toast::before {
  content: '';
  position: absolute;
  left: 0;
  top: 13px;
  width: 3px;
  height: 14px;
  background: var(--tone);
  box-shadow: 0 0 8px var(--tone);
}
:global(.corners-cut) .toast {
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
:global(.corners-round) .toast {
  border-radius: 8px;
}
.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.ttl {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.3;
}
.x {
  flex: none;
  width: 24px;
  height: 24px;
  margin: -5px -6px 0 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  padding: 0;
  color: var(--color-dim);
}
.x:hover {
  color: var(--color-tx);
}
.foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sub {
  font: 11px/1.3 var(--font-mono);
  color: var(--color-dim);
}
.act {
  --cut: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--tone);
  background: transparent;
  color: var(--tone);
  font: 600 11px var(--font-sans);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.act:hover {
  background: color-mix(in oklch, var(--tone) 14%, transparent);
}
.act:disabled {
  opacity: 0.6;
}
/* the 2px timer along the bottom edge, draining over the toast's life */
.timer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: color-mix(in oklch, var(--tone) 18%, transparent);
}
.timer i {
  display: block;
  height: 100%;
  background: var(--tone);
  animation: drain 10s linear forwards;
  transform-origin: left;
}
@keyframes drain {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .timer i {
    animation: none;
  }
}
</style>
