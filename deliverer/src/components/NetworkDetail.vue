<script setup lang="ts">
import { areaPath, BASELINE, CHART_H, CHART_W, linePath, toPoints, yScale } from '@/lib/netchart';

/**
 * The network modal, from the rail card's ⓘ: the last 30 s of download and
 * upload as a chart, the three figures, and what the line is (edge server,
 * interface, SSID, ISP). The store polls the daemon once a second while
 * open, so each figure lands the moment its leg finishes and the chart
 * streams; every fifth second it runs a short probe so the tape keeps growing
 * while watched. Retest exists only when a probe failed or the line is down.
 * While the line is down (or before the first answer) the same modal wears a
 * rose border and a state chip, the chart stays empty, the figures read "-",
 * the box says what is known, and a line counts down to the next probe.
 * Esc and Close dismiss; Close has focus on open; Tab stays inside.
 */
const net = useNetwork();
const panel = ref<HTMLElement | null>(null);
const closeBtn = ref<HTMLButtonElement | null>(null);

const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString([], {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

const measured = computed(() => (net.speed?.measured_at ? clock(net.speed.measured_at * 1000) : '-'));
const lost = computed(() => (net.lostAt ? clock(net.lostAt) : '-'));
const ago = computed(() => net.lostAgo ?? 0);

/** the line is down or nothing has answered yet: the offline dress */
const down = computed(() => net.phase === 'checking' || !net.online);

const samples = computed(() => net.speed?.samples ?? { download: [], upload: [] });
const scale = computed(() => yScale(Math.max(0, ...samples.value.download, ...samples.value.upload)));
const downPts = computed(() => (down.value ? [] : toPoints(samples.value.download, scale.value)));
const upPts = computed(() => (down.value ? [] : toPoints(samples.value.upload, scale.value)));

/** "-" while the line is down or before a figure exists; a running test replaces each figure as its leg lands */
const fig = (v: number | null | undefined) => (down.value || v == null ? '-' : v.toFixed(1));
const count = computed(() => Math.max(samples.value.download.length, samples.value.upload.length));

const conn = computed(() => net.speed?.connection ?? null);
const server = computed(() => net.speed?.server ?? null);

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    net.hide();
    return;
  }
  if (e.key === 'Tab' && panel.value) {
    const items = [...panel.value.querySelectorAll<HTMLElement>('button:not(:disabled)')];
    if (!items.length) return;
    const i = items.indexOf(document.activeElement as HTMLElement);
    const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i >= items.length - 1 ? 0 : i + 1;
    e.preventDefault();
    items[next]?.focus();
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey, true);
  closeBtn.value?.focus();
});

onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <div class="scrim" @click="net.hide()" />
  <div
    ref="panel"
    class="modal"
    :class="{ down }"
    role="dialog"
    aria-modal="true"
    :aria-label="$t('app.network.title')"
  >
    <div class="head">
      <SignalBars :bars="net.bars" :tone="net.phase === 'degraded' ? 'ember' : 'moss'" />
      <span class="ttl">{{ $t('app.network.title') }}</span>
      <span v-if="down" class="state">{{ $t(`app.network.phase.${net.phase}`) }}</span>
      <span class="spacer" />
      <span class="when">
        <template v-if="net.phase === 'checking'">{{ $t('app.network.measuringShort') }}</template>
        <template v-else-if="down">
          {{ $t('app.network.lost', { time: lost }) }} ·
          {{
            ago < 60
              ? $t('app.network.ago', { s: ago })
              : $t('app.network.agoMin', { m: Math.floor(ago / 60) })
          }}
        </template>
        <template v-else>{{ $t('app.network.measured', { time: measured }) }}</template>
      </span>
    </div>

    <div class="body">
      <div class="chart-block">
        <div class="legend">
          <span>
            <i class="sw ember" />
            {{ $t('app.network.legend.download') }}
          </span>
          <span>
            <i class="sw moss" />
            {{ $t('app.network.legend.upload') }}
          </span>
          <span class="spacer" />
          <span class="win">
            {{ down ? $t('app.network.legend.none') : $t('app.network.legend.window', { n: count }) }}
          </span>
        </div>
        <svg
          class="chart"
          :viewBox="`0 0 ${CHART_W} ${CHART_H}`"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <line :x1="0" y1="22" :x2="CHART_W" y2="22" class="grid" />
          <line :x1="0" y1="54" :x2="CHART_W" y2="54" class="grid" />
          <path v-if="downPts.length > 1" :d="areaPath(downPts)" class="area ember" />
          <path v-if="upPts.length > 1" :d="areaPath(upPts)" class="area moss" />
          <path v-if="downPts.length > 1" :d="linePath(downPts)" class="line ember" />
          <path v-if="upPts.length > 1" :d="linePath(upPts)" class="line moss" />
          <line
            v-if="!downPts.length && !upPts.length"
            :x1="0"
            :y1="BASELINE"
            :x2="CHART_W"
            :y2="BASELINE"
            class="grid"
          />
        </svg>
      </div>

      <div class="stats">
        <div class="stat">
          <div class="lbl ember">{{ $t('app.network.stat.download') }}</div>
          <div class="val">
            {{ fig(net.speed?.download_mbps) }}
            <span class="unit">{{ $t('app.network.mbps') }}</span>
          </div>
        </div>
        <div class="stat">
          <div class="lbl moss">{{ $t('app.network.stat.upload') }}</div>
          <div class="val">
            {{ fig(net.speed?.upload_mbps) }}
            <span class="unit">{{ $t('app.network.mbps') }}</span>
          </div>
        </div>
        <div class="stat">
          <div class="lbl">{{ $t('app.network.stat.latency') }}</div>
          <div class="val">
            {{ fig(net.speed?.latency_ms) }}
            <span class="unit">{{ $t('app.network.ms') }}</span>
          </div>
        </div>
      </div>

      <div class="conn">
        <div class="row">
          <i class="dot" :class="net.online ? 'moss' : 'rose'" aria-hidden="true" />
          <span v-if="net.online">
            {{ $t('app.network.server') }}
            <b>{{ server?.location ?? '-' }}</b>
            <template v-if="server?.ip_version">· {{ server.ip_version }}</template>
          </span>
          <span v-else>
            {{ $t('app.network.server') }}
            <b class="rose">{{ $t('app.network.unreachable') }}</b>
            <template v-if="server?.location">
              · {{ $t('app.network.last', { location: server.location }) }}
            </template>
            <template v-if="server?.ip_version">· {{ server.ip_version }}</template>
          </span>
        </div>
        <div class="row">
          <i class="dot" :class="conn?.interface ? 'moss' : 'rose'" aria-hidden="true" />
          <span>
            {{ $t(`app.network.iface.${conn?.interface ?? 'other'}`) }}
            <b v-if="conn?.ssid">{{ conn.ssid }}</b>
            <template v-if="conn?.isp">· {{ conn.isp }}</template>
            <span v-if="conn?.asn" class="asn">{{ conn.asn }}</span>
            <template v-if="!net.online && !conn?.isp">
              · {{ $t('app.network.provider') }}
              <b class="rose">{{ $t('app.network.unknown') }}</b>
              -
              {{ $t('app.network.noRoute') }}
            </template>
          </span>
        </div>
        <div v-if="net.speed?.error" class="row err">
          <i class="dot rose" aria-hidden="true" />
          <span>{{ net.speed.error }}</span>
        </div>
      </div>

      <div v-if="down && net.phase !== 'checking'" class="row retry">
        <i class="dot ember" aria-hidden="true" />
        <span>{{ $t('app.network.offlineLine', { s: net.retryIn }) }}</span>
      </div>
    </div>

    <div class="foot">
      <span class="hint">{{ $t('app.network.hint') }}</span>
      <span class="spacer" />
      <!-- probes run by themselves while the modal is open; a button only when one failed -->
      <button
        v-if="(down || net.speed?.error) && !net.testing"
        type="button"
        class="btn gh"
        @click="net.measure(true)"
      >
        <Icon name="refresh" :size="13" />
        {{ down ? $t('app.network.retryNow') : $t('app.network.retest') }}
      </button>
      <button ref="closeBtn" type="button" class="btn pri" @click="net.hide()">
        {{ $t('app.network.close') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: oklch(0.1 0.02 265 / 0.72);
  backdrop-filter: blur(3px);
}
.modal {
  --cut: 12px;
  --edge: oklch(0.74 0.198 196);
  position: fixed;
  z-index: 41;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: min(440px, 92vw);
  display: flex;
  flex-direction: column;
  background: var(--surf);
  border: 1px solid color-mix(in oklch, var(--edge) 45%, transparent);
  box-shadow:
    0 0 0 1px color-mix(in oklch, var(--edge) 30%, transparent),
    0 34px 80px oklch(0.08 0.02 265 / 0.7);
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.modal.down {
  --edge: var(--rose);
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--line-soft);
}
.ttl {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.state {
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--rose);
  border: 1px solid var(--rose);
  padding: 3px 9px;
  white-space: nowrap;
}
.when,
.legend,
.win,
.hint,
.val,
.asn {
  font-family: var(--mono);
}
.when {
  font-size: 10.5px;
  color: var(--dim);
  white-space: nowrap;
}
.body {
  padding: 17px 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.chart-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.legend {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 10.5px;
  color: var(--mut);
}
.legend > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sw {
  display: inline-block;
  width: 10px;
  height: 2px;
}
.sw.ember {
  background: var(--ember);
}
.sw.moss {
  background: var(--moss);
}
.win {
  font-size: 10px;
  color: var(--dim);
}
.chart {
  display: block;
  width: 100%;
  height: 110px;
  border: 1px solid var(--line-soft);
  background: var(--bg);
}
.grid {
  stroke: oklch(0.26 0.024 265);
  stroke-width: 1;
  stroke-dasharray: 2 4;
  vector-effect: non-scaling-stroke;
}
.line {
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
.line.ember {
  stroke: var(--ember);
}
.line.moss {
  stroke: var(--moss);
}
.area {
  stroke: none;
}
.area.ember {
  fill: color-mix(in oklch, var(--ember) 14%, transparent);
}
.area.moss {
  fill: color-mix(in oklch, var(--moss) 14%, transparent);
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.stat {
  border: 1px solid var(--line-soft);
  background: var(--bg);
  padding: 10px 12px;
  min-width: 0;
}
.lbl {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--mut);
  margin-bottom: 8px;
  white-space: nowrap;
}
.lbl.ember {
  color: var(--ember);
}
.lbl.moss {
  color: var(--moss);
}
.val {
  font-size: 20px;
  line-height: 1;
  color: var(--tx);
  white-space: nowrap;
}
.unit {
  font-size: 10.5px;
  color: var(--dim);
  margin-left: 4px;
}
.conn {
  border: 1px solid var(--line-soft);
  background: var(--bg);
  padding: 11px 13px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.row {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  color: var(--mut);
  min-width: 0;
}
.row > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row b {
  color: var(--tx);
  font-weight: 500;
}
.row b.rose {
  color: var(--rose);
}
.row.err {
  color: var(--rose);
}
.row.err > span {
  white-space: normal;
}
.row.retry {
  margin-top: -4px;
}
.asn {
  font-size: 11px;
  color: var(--dim);
  margin-left: 6px;
}
.dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.dot.moss {
  background: var(--moss);
}
.dot.rose {
  background: var(--rose);
}
.dot.ember {
  background: var(--ember);
  box-shadow: 0 0 8px color-mix(in oklch, var(--ember) 60%, transparent);
}
.foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 18px;
  border-top: 1px solid var(--line-soft);
}
.hint {
  font-size: 10.5px;
  color: var(--dim);
}
.foot .btn {
  min-width: 92px;
  justify-content: center;
}
.spin {
  animation: net-spin 1s linear infinite;
}
@keyframes net-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }
}
</style>
