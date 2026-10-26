<script setup lang="ts">
/**
 * The rail's signal card, above Shutdown: bars and the download figure from
 * the daemon's last probe (stores/network.ts, every 30 s), and the ⓘ that
 * opens NetworkDetail. Five states: checking (before the first answer),
 * disconnected (no interface), no internet (an interface, no route: the
 * countdown says when the next probe is due), degraded (one bar or a slow
 * round trip, in ember), ok.
 */
const net = useNetwork();
const latency = computed(() => (net.speed?.latency_ms == null ? null : Math.round(net.speed.latency_ms)));
const { t } = useI18n();

const linkName = computed(() => {
  const c = net.speed?.connection;
  return c?.ssid || t(`app.network.iface.${c?.interface ?? 'other'}`);
});
</script>

<template>
  <div class="netcard" :class="net.phase">
    <Icon v-if="net.phase === 'disconnected'" name="wifi-off" class="off" :size="18" />
    <SignalBars v-else :bars="net.bars" :tone="net.phase === 'degraded' ? 'ember' : 'moss'" />
    <div class="txt">
      <template v-if="net.phase === 'checking'">
        <div class="l1">{{ $t('app.network.checking') }}</div>
        <div class="l2">{{ $t('app.network.measuring') }}</div>
      </template>
      <template v-else-if="net.phase === 'disconnected'">
        <div class="l1 rose">{{ $t('app.network.disconnected') }}</div>
        <div class="l2">{{ $t('app.network.noNetwork') }}</div>
      </template>
      <template v-else-if="net.phase === 'noInternet'">
        <div class="l1 rose">{{ $t('app.network.noInternet') }}</div>
        <div class="l2">{{ $t('app.network.retrying', { name: linkName, s: net.retryIn }) }}</div>
      </template>
      <template v-else>
        <div class="l1">
          <span aria-hidden="true">↓</span>
          {{ net.download?.toFixed(1) }}
          <span class="unit">{{ $t('app.network.mbps') }}</span>
        </div>
        <div class="l2" :class="{ ember: net.phase === 'degraded' }">
          {{
            latency != null
              ? $t('app.network.summary', { quality: $t(`app.network.quality.${net.quality}`), ms: latency })
              : '-'
          }}
        </div>
      </template>
    </div>
    <button
      type="button"
      class="info"
      :aria-label="$t('app.network.details')"
      :title="$t('app.network.details')"
      @click="net.show()"
    >
      <Icon name="info" :size="14" />
    </button>
  </div>
</template>

<style scoped>
.netcard {
  --cut: 6px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid var(--line-soft);
  background: var(--surf);
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.netcard.noInternet {
  border-bottom-color: color-mix(in oklch, var(--rose) 70%, var(--line-soft));
}
.netcard.disconnected {
  border-top-color: color-mix(in oklch, var(--rose) 70%, var(--line-soft));
}
.off {
  flex: none;
  color: var(--rose);
}
.txt {
  flex: 1;
  min-width: 0;
  font-family: var(--mono);
  line-height: 1.3;
}
.l1 {
  font-size: 11.5px;
  color: var(--tx);
  white-space: nowrap;
}
.l1.rose {
  color: var(--rose);
}
.unit {
  font-size: 10px;
  color: var(--dim);
}
.l2 {
  font-size: 10px;
  color: var(--dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.l2.ember {
  color: var(--ember);
}
.info {
  flex: none;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--mut);
  cursor: pointer;
  padding: 0;
  transition:
    color 0.1s,
    border-color 0.1s;
}
.info:hover,
.info:focus-visible {
  color: var(--cyan);
  border-color: var(--cyan);
  outline: none;
}
</style>
