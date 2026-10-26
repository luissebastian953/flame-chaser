<script setup lang="ts">
/** Settings › Updates: status, auto-install, build facts, patch history from CHANGELOG.md. */
import changelog from '../../../CHANGELOG.md?raw';

const { t } = useI18n();
const up = useUpdater();
const ep = useEndpoint();

const auto = computed({ get: () => up.auto, set: (v) => up.setAuto(v) });

const ago = (ts: number | null) => {
  if (!ts) return t('updates.panel.ago.never');
  const m = Math.round((Date.now() - ts) / 60000);
  return m < 1
    ? t('updates.panel.ago.justNow')
    : m < 60
      ? t('updates.panel.ago.minutes', { n: m })
      : t('updates.panel.ago.hours', { n: Math.round(m / 60) });
};

const until = (ts: number | null) => {
  if (!ts) return t('updates.panel.until.nextLaunch');
  const h = Math.max(0, Math.round((ts - Date.now()) / 3600000));
  return h < 1 ? t('updates.panel.until.withinHour') : t('updates.panel.until.hours', { n: h });
};

// ---- CHANGELOG.md → [{version, date, items:[{kind, text}]}] ---------------
interface Entry {
  version: string;
  date: string;
  items: { kind: string; text: string }[];
}

const history = computed<Entry[]>(() => {
  const out: Entry[] = [];
  let cur: Entry | null = null;
  for (const raw of changelog.split('\n')) {
    const h = /^## (\S+)(?:\s+-\s+(\S+))?/.exec(raw);
    if (h) {
      cur = { version: h[1]!, date: h[2] ?? '', items: [] };
      out.push(cur);
      continue;
    }
    const li = /^- (Added|Changed|Fixed|Removed):\s+(.*)$/.exec(raw);
    if (li && cur) cur.items.push({ kind: li[1]!, text: li[2]! });
  }
  return out.filter((e) => e.items.length);
});

const kindColor: Record<string, string> = {
  Added: 'var(--ember)',
  Changed: 'var(--cyan)',
  Fixed: 'var(--moss)',
  Removed: 'var(--rose)',
};

type Status = 'inDevelopment' | 'installed' | 'superseded';

const status = (v: string): Status =>
  v === 'Unreleased' ? 'inDevelopment' : v === up.current ? 'installed' : 'superseded';

const statusKey: Record<Status, string> = {
  inDevelopment: 'updates.panel.inDevelopment',
  installed: 'updates.panel.installedTag',
  superseded: 'updates.panel.superseded',
};
</script>

<template>
  <div class="flex flex-col gap-15 flex-1">
    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('updates.panel.title') }}</span>
        <span class="data text-small text-dim ml-10">{{ $t('updates.panel.cadence') }}</span>
        <div class="spacer" />
        <button
          class="btn gh sm"
          :disabled="up.phase === 'checking' || up.phase === 'unsupported'"
          @click="up.check()"
        >
          <Icon name="refresh" :size="13" :class="{ spin: up.phase === 'checking' }" />
          {{ up.phase === 'checking' ? $t('updates.panel.checking') : $t('updates.panel.checkNow') }}
        </button>
      </div>
      <div class="p-15 flex flex-col gap-15">
        <div class="status" :class="{ warn: up.phase === 'error' || up.daemonMismatch }">
          <span
            class="ic"
            :class="
              up.phase === 'available' || up.phase === 'ready' ? 'cy' : up.phase === 'error' ? 'rose' : 'ok'
            "
          >
            <Icon v-if="up.phase === 'available' || up.phase === 'ready'" name="update" :size="26" />
            <Icon v-else-if="up.phase === 'error'" name="error" :size="26" />
            <Icon v-else name="success" :size="26" />
          </span>
          <div class="flex-1 min-w-0">
            <div class="text-base font-semibold">
              <template v-if="up.phase === 'unsupported'">
                {{ $t('updates.panel.browserMode', { version: up.current }) }}
              </template>
              <template v-else-if="up.phase === 'available'">
                {{ $t('updates.panel.available', { version: up.version }) }}
              </template>
              <template v-else-if="up.phase === 'downloading'">
                {{ $t('updates.panel.downloading', { version: up.version, pct: up.progress }) }}
              </template>
              <template v-else-if="up.phase === 'ready' || up.phase === 'waiting'">
                {{ $t('updates.panel.readyRestart', { version: up.version }) }}
              </template>
              <template v-else-if="up.phase === 'error'">{{ $t('updates.panel.failed') }}</template>
              <template v-else>{{ $t('updates.panel.upToDate', { version: up.current }) }}</template>
            </div>
            <div class="data text-small text-dim">
              <template v-if="up.phase === 'error'">{{ up.error }}</template>
              <template v-else>
                {{ $t('updates.panel.lastChecked', { ago: ago(up.lastChecked), next: until(up.nextCheck) }) }}
              </template>
            </div>
            <div v-if="up.daemonMismatch" class="err text-small mt-5">
              {{ $t('updates.panel.mismatch', { app: up.current, daemon: ep.health?.version }) }}
            </div>
          </div>
          <button v-if="up.phase === 'available'" class="btn pri sm" @click="up.download()">
            <Icon name="download" :size="13" />
            {{ $t('updates.panel.download') }}
          </button>
          <button v-else-if="up.phase === 'ready'" class="btn pri sm" @click="up.install()">
            <Icon name="refresh" :size="13" />
            {{ $t('updates.panel.restartNow') }}
          </button>
          <div v-else class="flex items-center gap-10">
            <SwitchRoot id="auto" v-model="auto" class="rk-switch" :disabled="up.phase === 'unsupported'">
              <SwitchThumb class="rk-switch-thumb" />
            </SwitchRoot>
            <label for="auto" class="text-small">{{ $t('updates.panel.auto') }}</label>
          </div>
        </div>
        <div class="facts">
          <div>
            <label>{{ $t('updates.panel.installed') }}</label>
            <span class="data">{{ up.current }}</span>
          </div>
          <div>
            <label>{{ $t('updates.panel.channel') }}</label>
            <span class="data">{{ $t('updates.panel.stable') }}</span>
          </div>
          <div>
            <label>{{ $t('updates.panel.build') }}</label>
            <span class="data">{{ up.build }}</span>
          </div>
          <div>
            <label>{{ $t('updates.panel.crawler') }}</label>
            <span class="data">{{ ep.health?.version ?? '-' }}</span>
          </div>
          <div>
            <label>{{ $t('updates.panel.database') }}</label>
            <span class="data">
              {{ $t('updates.panel.schema', { n: ep.health?.schema_version ?? '-' }) }}
            </span>
          </div>
        </div>
        <div class="hint">{{ $t('updates.panel.idleNote') }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('updates.panel.history') }}</span>
        <span class="data text-small text-dim ml-10">{{ $t('updates.panel.historySub') }}</span>
      </div>
      <div class="p-15 flex flex-col">
        <div v-for="e in history" :key="e.version" class="rel">
          <div class="ver">
            <div class="data text-medium">
              {{ e.version === 'Unreleased' ? $t('updates.panel.next') : e.version }}
            </div>
            <div class="data text-small text-dim">{{ e.date || $t('updates.panel.unreleased') }}</div>
            <span class="chip mt-5" :class="status(e.version) === 'installed' ? 'on' : 'off'">
              {{ $t(statusKey[status(e.version)]) }}
            </span>
          </div>
          <ul class="items">
            <li v-for="(it, i) in e.items" :key="i">
              <span class="dot" :style="{ background: kindColor[it.kind] }" />
              <b>{{ it.kind }}</b>
              {{ it.text }}
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.status {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--line-soft);
  background: var(--bg);
}
.status.warn {
  border-color: color-mix(in oklch, var(--rose) 45%, transparent);
}
.ic {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
}
.ic.ok {
  color: var(--moss);
}
.ic.cy {
  color: var(--cyan);
}
.ic.rose {
  color: var(--rose);
}
.facts {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 15px;
}
.facts label {
  display: block;
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 4px;
}
.rel {
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 20px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line-soft);
}
.rel:last-child {
  border-bottom: 0;
}
.ver .chip {
  display: inline-flex;
}
.items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.items li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
  color: var(--mut);
}
.items b {
  color: var(--tx);
  font-weight: 600;
}
.items .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
  transform: translateY(-2px);
}
</style>
