<script setup lang="ts">
const ep = useEndpoint();
const jobs = useJobs();
const lib = useLibrary();
const src = useSources();
const up = useUpdater();
const viewer = useViewer();
const net = useNetwork();
useTheme().apply(); // before first paint: no flash of default palette
useBackgroundController(); // mini window, tray, notifications; desktop only

// Desktop only: the browser build has no process to end. The button opens
// ShutdownConfirm, which says what is running before anything is cut.
const asking = ref(false);

async function shutdown() {
  asking.value = false;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('shutdown_app');
}

onMounted(async () => {
  await ep.boot();
  if (ep.ready) {
    jobs.listen();
    await Promise.all([jobs.load(), lib.loadWatches(), src.load()]);
    up.schedule(); // daily check; desktop only
    net.start(); // the rail's signal card, every 30 s
  }
});
</script>

<template>
  <div class="layout">
    <aside class="rail">
      <div class="brand">
        <BrandMark :size="22" class="mark" />
        <div>
          <b>{{ $t('app.brand.name') }}</b>
          <span>{{ $t('app.brand.tagline') }}</span>
        </div>
      </div>
      <nav class="nav">
        <RouterLink to="/config">
          <Icon name="crawl" class="ic" />
          {{ $t('app.nav.crawl') }}
          <span class="ct">{{ lib.watches.length || '' }}</span>
        </RouterLink>
        <RouterLink to="/pipeline">
          <Icon name="pipeline" class="ic" />
          {{ $t('app.nav.pipeline') }}
          <span class="ct">
            <i v-if="jobs.running.length" class="live" aria-hidden="true" />
            {{ jobs.queued.length + jobs.running.length || '' }}
          </span>
        </RouterLink>
        <RouterLink to="/gallery">
          <Icon name="gallery" class="ic" />
          {{ $t('app.nav.gallery') }}
          <span class="ct">{{ lib.totalPosts ? lib.totalPosts.toLocaleString() : '' }}</span>
        </RouterLink>
        <RouterLink to="/settings">
          <Icon name="settings" class="ic" />
          {{ $t('app.nav.settings') }}
        </RouterLink>
      </nav>
      <div class="railbottom">
        <UpdateBanner />
        <NetworkCard v-if="ep.ready" />
        <button v-if="src.inTauri" class="btn danger shutdown" @click="asking = true">
          <Icon name="power" class="ic" :size="14" />
          {{ $t('app.shutdown.label') }}
        </button>
        <div class="railfoot">
          <div>
            <Icon
              name="server"
              class="fi"
              :size="12"
              :style="{ color: ep.ready ? 'var(--moss)' : 'var(--rose)' }"
            />
            {{
              ep.ready
                ? $t('app.status.daemon', { version: ep.health?.version })
                : ep.error
                  ? $t('app.status.unreachable')
                  : $t('app.status.connecting')
            }}
          </div>
          <div v-if="ep.health">
            <Icon v-if="ep.health.idle" name="cpu" class="fi" :size="12" />
            <Icon v-else name="loader" class="fi spin" :size="12" style="color: var(--ember)" />
            {{ ep.health.idle ? $t('app.status.idle') : $t('app.status.crawling') }}
          </div>
          <div v-if="src.status">
            <Icon v-if="src.pixivOk" name="unlock" class="fi" :size="12" style="color: var(--moss)" />
            <Icon v-else name="lock" class="fi" :size="12" />
            {{
              $t('app.status.pixiv', {
                state: src.pixivOk
                  ? $t('app.status.connected')
                  : src.pixivPending
                    ? $t('app.status.checking')
                    : src.status.pixiv.verified === false
                      ? $t('app.status.expired')
                      : $t('app.status.notLinked'),
              })
            }}
          </div>
          <div v-if="src.status">
            <Icon v-if="src.twitterOk" name="unlock" class="fi" :size="12" style="color: var(--moss)" />
            <Icon v-else name="lock" class="fi" :size="12" />
            {{
              $t('app.status.x', {
                state: src.twitterOk ? $t('app.status.connected') : $t('app.status.notLinked'),
              })
            }}
          </div>
        </div>
      </div>
    </aside>
    <main class="main">
      <div v-if="ep.error" class="empty err">{{ ep.error }}</div>
      <template v-else-if="ep.ready">
        <RouterView />
        <RunToasts />
        <AuthGate v-if="src.needsGate" />
      </template>
      <div v-else class="empty">{{ $t('app.connectingDaemon') }}</div>
    </main>
  </div>
  <!-- over everything, the rail included -->
  <ImageViewer v-if="viewer.open" />
  <ShutdownConfirm v-if="asking" @close="asking = false" @confirm="shutdown" />
  <NetworkDetail v-if="net.open" />
</template>
