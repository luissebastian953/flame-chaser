<script setup lang="ts">
/** Inline session state next to a section title. Click = connect. */
defineProps<{ state: 'on' | 'off' | 'expired' }>();
const emit = defineEmits<{ connect: [] }>();
</script>

<template>
  <span v-if="state === 'on'" class="badge ok">
    <Icon name="shield" :size="13" />
    {{ $t('auth.badge.on') }}
  </span>
  <button
    v-else
    class="badge need"
    type="button"
    :title="state === 'expired' ? $t('auth.badge.titleExpired') : $t('auth.badge.titleConnect')"
    @click="emit('connect')"
  >
    <Icon v-if="state === 'expired'" name="warning" :size="13" />
    <Icon v-else name="lock" :size="13" />
    {{ state === 'expired' ? $t('auth.badge.expired') : $t('auth.badge.required') }}
  </button>
</template>

<style scoped>
.badge {
  --cut: 5px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 24px;
  padding: 0 12px 0 10px;
  margin-left: 4px;
  font: 600 11px var(--font);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 1px solid;
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.ok {
  color: var(--moss);
  border-color: color-mix(in oklch, var(--moss) 45%, transparent);
  background: color-mix(in oklch, var(--moss) 12%, transparent);
}
.need {
  color: var(--cyan);
  border-color: color-mix(in oklch, var(--cyan) 45%, transparent);
  background: color-mix(in oklch, var(--cyan) 12%, transparent);
  cursor: pointer;
}
.need:hover {
  background: color-mix(in oklch, var(--cyan) 20%, transparent);
}
</style>
