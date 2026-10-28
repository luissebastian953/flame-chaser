<script setup lang="ts">
import type { StorageUsage, TrashSummary } from '@/lib/types';

/**
 * Settings › Storage: four plates on a two-column grid (one column under
 * 1000 px). Library (path, reveal, the disk bar), Database (path, size, the
 * load-bearing rule as a shield hint), Layout (the three trees with their
 * counts) and Trash (count, size, the 30-day rule, Empty). The versions
 * sit in the panel header's right slot. Figures come from GET /api/storage
 * (coreflame/library.py usage) and GET /api/trash. A full-width Purge
 * all data plate closes the grid; its sheet is PurgeSheet, and it is off
 * while a crawl, export or import is queued or running.
 */
const { t } = useI18n();
const fm = useFormats();
const ep = useEndpoint();
const up = useUpdater();
const jobs = useJobs();
const lib = useLibrary();

const desktop = '__TAURI_INTERNALS__' in window;

const usage = ref<StorageUsage | null>(null);
const trash = ref<TrashSummary | null>(null);
const emptied = ref<number | null>(null);
const error = ref('');

async function load() {
  try {
    [usage.value, trash.value] = await Promise.all([
      api.get<StorageUsage>('/api/storage'),
      api.get<TrashSummary>('/api/trash').catch(() => null),
    ]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(() => {
  void load();
  jobs.load().catch(() => {});
});

// ---- purge all data ----------------------------------------------------------
const purging = ref(false);
const purged = ref<{ images: number; bytes: number; failed: number } | null>(null);
/** the daemon refuses with 409 too; this says why before the click */
const busy = computed(() => jobs.running.length > 0 || jobs.queued.length > 0);

async function onPurged(r: { images: number; bytes: number; failed: string[] }) {
  purging.value = false;
  purged.value = { images: r.images, bytes: r.bytes, failed: r.failed.length };
  emptied.value = null;
  await Promise.all([load(), lib.loadWatches().catch(() => {})]);
}

/** share of the disk, in percent, clamped so the bar never overflows */
const pct = (n: number) => (usage.value ? Math.min(100, (100 * n) / Math.max(1, usage.value.disk.total)) : 0);

async function emptyTrash() {
  try {
    const r = await api.post<{ images: number; bytes: number }>('/api/trash/purge', { everything: true });
    emptied.value = r.images;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function reveal() {
  if (usage.value) await revealInFolder(usage.value.library_root).catch(() => {});
}

const versions = computed(() =>
  t('settings.storage.versions', {
    app: up.current,
    daemon: ep.health?.version ?? '',
    schema: usage.value?.schema_version ?? ep.health?.schema_version ?? '',
  }),
);
</script>

<template>
  <div class="panel">
    <div class="phead">
      <span class="ptitle">{{ $t('settings.storage.title') }}</span>
      <span class="data text-small text-dim">{{ $t('settings.storage.sub') }}</span>
      <div class="spacer" />
      <span class="data text-small text-dim">{{ versions }}</span>
    </div>
    <div v-if="usage" class="plates">
      <!-- LIBRARY -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="folder" :size="13" />
          <b>{{ $t('settings.storage.library') }}</b>
          <div class="spacer" />
          <button v-if="desktop" class="btn sm" @click="reveal">{{ $t('settings.storage.reveal') }}</button>
        </div>
        <div class="path" :title="usage.library_root">{{ usage.library_root }}</div>
        <div class="disk">
          <div
            class="bar"
            role="img"
            :aria-label="
              $t('settings.storage.diskFree', {
                free: fm.bytes(usage.disk.free),
                total: fm.bytes(usage.disk.total),
                mount: usage.disk.mount,
              })
            "
          >
            <i class="lib" :style="{ width: pct(usage.disk.library) + '%' }" />
            <i class="other" :style="{ width: pct(usage.disk.other) + '%' }" />
          </div>
          <div class="legend">
            <span>
              <em class="lib" />
              {{ $t('settings.storage.diskLibrary', { size: fm.bytes(usage.disk.library) }) }}
            </span>
            <span>
              <em class="other" />
              {{ $t('settings.storage.diskOther', { size: fm.bytes(usage.disk.other) }) }}
            </span>
            <span>
              <em class="free" />
              {{
                $t('settings.storage.diskFree', {
                  free: fm.bytes(usage.disk.free),
                  total: fm.bytes(usage.disk.total),
                  mount: usage.disk.mount,
                })
              }}
            </span>
          </div>
        </div>
      </section>

      <!-- DATABASE -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="database" :size="13" />
          <b>{{ $t('settings.storage.database') }}</b>
          <div class="spacer" />
          <span class="data text-small text-mut">
            {{
              $t('settings.storage.databaseMeta', {
                size: fm.bytes(usage.db_bytes),
                schema: usage.schema_version,
              })
            }}
          </span>
        </div>
        <div class="path" :title="usage.db_path">{{ usage.db_path }}</div>
        <div class="inset rule">
          <Icon name="shield" :size="13" />
          <span>{{ $t('settings.storage.hint') }}</span>
        </div>
      </section>

      <!-- LAYOUT -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="list" :size="13" />
          <b>{{ $t('settings.storage.layout') }}</b>
        </div>
        <div class="inset lay">
          <div>
            <b>blobs/</b>
            <s>{{ $t('settings.storage.blobs') }}</s>
            <u>
              {{
                $t(
                  'settings.storage.blobsValue',
                  { n: fm.number(usage.blobs.files), size: fm.bytes(usage.blobs.bytes) },
                  usage.blobs.files,
                )
              }}
            </u>
          </div>
          <div>
            <b>by-character/</b>
            <s>{{ $t('settings.storage.byCharacter') }}</s>
            <u>
              {{
                $t(
                  'settings.storage.byCharacterValue',
                  { n: usage.by_character.characters },
                  usage.by_character.characters,
                )
              }}
            </u>
          </div>
          <div>
            <b>thumbs/</b>
            <s>{{ $t('settings.storage.thumbs') }}</s>
            <u>
              {{
                $t('settings.storage.thumbsValue', {
                  n: fm.number(usage.thumbs.files),
                  size: fm.bytes(usage.thumbs.bytes),
                })
              }}
            </u>
          </div>
        </div>
      </section>

      <!-- TRASH -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="trash" :size="13" />
          <b>{{ $t('settings.storage.trash') }}</b>
          <div class="spacer" />
          <button v-if="trash?.count" class="btn sm danger" @click="emptyTrash">
            {{ $t('settings.storage.emptyTrash') }}
          </button>
        </div>
        <div class="data text-base" :class="{ 'text-dim': !trash?.count }">
          <template v-if="trash?.count">
            {{
              $t('settings.storage.trashValue', { n: trash.count, size: fm.bytes(trash.bytes) }, trash.count)
            }}
          </template>
          <template v-else>{{ $t('settings.storage.trashEmpty') }}</template>
        </div>
        <div class="data text-small text-mut">
          {{ $t('settings.storage.trashKept', { days: trash?.days ?? 30 }) }}
          <template v-if="emptied !== null">
            · {{ $t('settings.storage.trashEmptied', { n: emptied }, emptied) }}
          </template>
        </div>
      </section>

      <!-- PURGE ALL DATA -->
      <section class="plate cut purge">
        <Icon name="warning" :size="13" class="text-rose" />
        <div class="pt">
          <div class="text-base text-tx">{{ $t('settings.storage.purge.title') }}</div>
          <div class="data text-small text-mut">{{ $t('settings.storage.purge.desc') }}</div>
          <div v-if="busy" class="data text-small text-dim">{{ $t('settings.storage.purge.busy') }}</div>
          <div v-else-if="purged" class="data text-small text-tx">
            {{
              $t('settings.storage.purge.done', {
                images: fm.number(purged.images),
                size: fm.bytes(purged.bytes),
              })
            }}
            <template v-if="purged.failed">
              ·
              <span class="text-rose">
                {{ $t('settings.storage.purge.failedFiles', { n: purged.failed }, purged.failed) }}
              </span>
            </template>
          </div>
        </div>
        <button class="btn danger purge-btn" :disabled="busy" @click="purging = true">
          {{ $t('settings.storage.purge.button') }}
        </button>
      </section>
    </div>
    <div v-else class="empty">{{ error || $t('settings.storage.loading') }}</div>
  </div>
  <!-- beside the panel, not in it: its container query would trap a fixed sheet -->
  <PurgeSheet v-if="purging" @close="purging = false" @done="onPurged" />
</template>

<style scoped>
.plate.purge {
  grid-column: 1 / -1;
  flex-direction: row;
  align-items: center;
  gap: 12px;
}
.plate.purge > svg {
  flex: none;
}
.pt {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.purge-btn {
  flex: none;
  margin-left: auto;
}
.purge-btn:disabled {
  opacity: 0.35;
}
@container (max-width: 1000px) {
  .plate.purge {
    flex-wrap: wrap;
  }
}
.plates {
  position: relative;
  z-index: 1;
  padding: 20px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 15px;
}
@container (max-width: 1000px) {
  .plates {
    grid-template-columns: minmax(0, 1fr);
  }
}
.panel {
  container-type: inline-size;
}
.plate {
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.plh {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 25px;
  color: var(--color-mut);
}
.plh b {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--color-dim);
}
.path {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-tx);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inset {
  background: var(--color-surf);
  border: 1px solid var(--color-line-soft);
}
.rule {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-mut);
}
.rule svg {
  flex: none;
  margin-top: 3px;
}
.disk {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.bar {
  height: 4px;
  display: flex;
  background: var(--color-surf);
  border: 1px solid var(--color-line-soft);
}
.bar i {
  display: block;
  height: 100%;
}
.lib {
  background: var(--color-ember);
}
.other {
  background: var(--color-line);
}
em.free {
  background: var(--color-surf);
  border: 1px solid var(--color-line-soft);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 15px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-dim);
}
.legend span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.legend em {
  width: 8px;
  height: 8px;
  display: inline-block;
}
.lay {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.lay > div {
  padding: 10px 15px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  border-left: 1px solid var(--color-line-soft);
  min-width: 0;
}
.lay > div:first-child {
  border-left: none;
}
.lay b {
  font: 500 14px var(--font-mono);
  color: var(--color-tx);
}
.lay s {
  text-decoration: none;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--color-mut);
}
.lay u {
  text-decoration: none;
  font: 12px var(--font-mono);
  color: var(--color-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
