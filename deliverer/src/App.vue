<script setup lang="ts">
const ep = useEndpoint();
const jobs = useJobs();
const lib = useLibrary();
const src = useSources();
const up = useUpdater();
useTheme().apply(); // before first paint: no flash of default palette

// Desktop only: the browser build has no process to end. Two-step when a
// crawl is running so a stray click doesn't cut a backfill mid-page.
const armed = ref(false);

async function shutdown() {
  if (ep.health && !ep.health.idle && !armed.value) {
    armed.value = true;
    setTimeout(() => (armed.value = false), 4000);
    return;
  }
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('shutdown_app');
}

onMounted(async () => {
  await ep.boot();
  if (ep.ready) {
    jobs.listen();
    await Promise.all([jobs.load(), lib.loadWatches(), src.load()]);
    up.schedule(); // daily check; desktop only
  }
});
</script>

<template>
  <div class="layout">
    <aside class="rail">
      <div class="brand">
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--ember)"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M4.5 19.5h15" />
          <path d="M7 19.5v-6.6a5 5 0 0 1 10 0v6.6" />
          <circle cx="12" cy="5.4" r="1.3" />
          <circle cx="12" cy="15.2" r="2.5" fill="var(--ember)" stroke="none" />
        </svg>
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
          <span class="ct">{{ jobs.queued.length + (jobs.running ? 1 : 0) || '' }}</span>
        </RouterLink>
        <RouterLink to="/gallery">
          <Icon name="gallery" class="ic" />
          {{ $t('app.nav.gallery') }}
          <span class="ct">{{ lib.totalPosts ? lib.totalPosts.toLocaleString() : '' }}</span>
        </RouterLink>
        <RouterLink to="/settings" class="mt-10">
          <Icon name="settings" class="ic" />
          {{ $t('app.nav.settings') }}
        </RouterLink>
      </nav>
      <div class="railbottom">
        <UpdateBanner />
        <button v-if="src.inTauri" class="btn danger shutdown" @click="shutdown">
          <Icon name="power" class="ic" :size="14" />
          {{ armed ? $t('app.shutdown.armed') : $t('app.shutdown.label') }}
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
        <AuthGate v-if="src.needsGate" />
      </template>
      <div v-else class="empty">{{ $t('app.connectingDaemon') }}</div>
    </main>
  </div>
</template>
