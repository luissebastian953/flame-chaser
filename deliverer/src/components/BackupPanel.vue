<script setup lang="ts">
import type { Job } from '@/lib/types';
import type {
  BundleExportBody,
  BundleFormat,
  BundleImportBody,
  BundleImportResult,
  BundleInspect,
  WatchPolicy,
} from '@/lib/types';

/**
 * Settings › Storage › Backup: the archive as one file, and back
 * (coreflame/bundle.py). Two plates. Export is a job on the `any` lane:
 * once a path is chosen the options fade and a job block under the action
 * row follows the four stages (snapshot · images · thumbs · verify) through
 * the jobs store, then stays as a receipt. Import reads the bundle first
 * (inspect), shows a sheet - mode, settings, one policy per character, the
 * pipeline gate - and runs inside one request; the result lines replace the
 * Import plate's body. Error cards name why a file could not be read.
 *
 * The webview's own state (theme, language, notification mode) rides along
 * as an opaque object (`lib/uiState.ts`): the daemon stores it, never reads
 * it, and hands it back when the bundle's settings are taken.
 */
const emit = defineEmits<{ updates: [] }>();
const { t, te } = useI18n();
const fm = useFormats();
const jobs = useJobs();
const lib = useLibrary();
const ep = useEndpoint();

const desktop = '__TAURI_INTERNALS__' in window;

// ---- export ----------------------------------------------------------------
const fmt = ref<BundleFormat>('curio');
const images = ref(true);
const thumbs = ref(true);
const secrets = ref(false);
const exportJobId = ref<string | null>(null);
const exportPath = ref<string | null>(null);
const exportError = ref('');
const copied = ref(false);

const exportJob = computed<Job | null>(
  () => (exportJobId.value && jobs.jobs.find((j) => j.id === exportJobId.value)) || null,
);

const exporting = computed(() => exportJob.value?.state === 'queued' || exportJob.value?.state === 'running');

/** the four stages with each one's own done / total (coreflame/bundle.py export) */
const STAGES = ['snapshot', 'images', 'thumbs', 'verify'] as const;

type Stage = (typeof STAGES)[number];

const TOTAL_OF: Record<Stage, string> = {
  snapshot: 'posts',
  images: 'images',
  thumbs: 'thumbs',
  verify: 'entries',
};

interface StageView {
  name: Stage;
  label: string;
  done: number;
  total: number | null;
  state: 'done' | 'run' | 'pending' | 'failed';
  pct: number;
}

const stages = computed<StageView[]>(() => {
  const j = exportJob.value;
  if (!j) return [];
  const cur = STAGES.indexOf(j.stage as Stage);
  const finished = j.state === 'succeeded';
  const broke = j.state === 'failed' || j.state === 'cancelled' || j.state === 'interrupted';
  return STAGES.map((name, i) => {
    const planned = j.counters[TOTAL_OF[name]] ?? null;
    const current = i === cur && !finished;
    const total = current ? (j.total ?? planned) : planned;
    let done = 0;
    let state: StageView['state'] = 'pending';
    if (finished || i < cur) {
      done = total ?? 0;
      state = 'done';
    } else if (current) {
      done = j.done;
      state = broke ? 'failed' : 'run';
    }
    const pct = state === 'done' ? 100 : total ? Math.min(100, (100 * done) / total) : 0;
    const key = `pipeline.stage.${name}`;
    return { name, label: te(key) ? t(key) : name, done, total, state, pct };
  });
});

const runningStage = computed(() => stages.value.find((s) => s.state === 'run') ?? null);

async function pickSavePath(): Promise<string | null | undefined> {
  if (!desktop) return undefined; // the daemon picks ~/.reaver/exports
  const { save } = await import('@tauri-apps/plugin-dialog');
  const stamp = new Date().toISOString().slice(0, 10);
  return save({
    defaultPath: `curio-${stamp}.${fmt.value}`,
    filters: [{ name: fmt.value === 'curio' ? 'Curio bundle' : 'Zip archive', extensions: [fmt.value] }],
  });
}

async function submitExport(path: string | undefined) {
  const body: BundleExportBody = {
    ...(path ? { path } : {}),
    format: fmt.value,
    images: images.value,
    thumbs: images.value && thumbs.value,
    secrets: secrets.value,
    ui: collectUiState(),
  };

  try {
    const r = await api.post<{ job_id: string; path: string }>('/api/bundle/export', body);
    exportJobId.value = r.job_id;
    exportPath.value = r.path;
    copied.value = false;
    await jobs.load();
  } catch (e) {
    exportError.value = e instanceof Error ? e.message : String(e);
  }
}

async function runExport() {
  exportError.value = '';
  let path: string | null | undefined;
  try {
    path = await pickSavePath();
  } catch (e) {
    exportError.value = e instanceof Error ? e.message : String(e);
    return;
  }
  if (path === null) return; // dialog dismissed
  await submitExport(path);
}

/** the same path again, no dialog */
async function retryExport() {
  exportError.value = '';
  await submitExport(desktop ? (exportPath.value ?? undefined) : undefined);
}

async function reveal() {
  if (exportPath.value) await revealInFolder(exportPath.value).catch(() => {});
}

async function copyPath() {
  if (!exportPath.value) return;
  try {
    await navigator.clipboard.writeText(exportPath.value);
    copied.value = true;
  } catch {
    copied.value = false;
  }
}

// ---- import: pick + inspect ---------------------------------------------------
type Phase = 'idle' | 'reading' | 'error' | 'result';

const phase = ref<Phase>('idle');
const importPath = ref('');
const importErr = ref<{ code: string; message: string } | null>(null);
const info = ref<BundleInspect | null>(null);
const result = ref<BundleImportResult | null>(null);
const resultMeta = ref<{ name: string; mode: 'merge' | 'restore' } | null>(null);
const showDamaged = ref(false);
const reloading = ref(false);

type ErrorKind = 'rose' | 'neutral' | 'fill' | 'dim';

const ERROR_KINDS: Record<string, ErrorKind> = {
  not_a_bundle: 'rose',
  bad_manifest: 'rose',
  bundle_too_new: 'neutral',
  damaged: 'fill',
  no_file: 'dim',
  busy: 'neutral',
};

const ERROR_ICON: Record<ErrorKind, string> = {
  rose: 'file',
  neutral: 'update',
  fill: 'warning',
  dim: 'close',
};

const errorKind = computed<ErrorKind>(() => (importErr.value && ERROR_KINDS[importErr.value.code]) || 'rose');

const fileName = (path: string) => path.split(/[\\/]/).pop() ?? path;

const errorTitle = computed(() => {
  const key = `settings.backup.import.errors.${importErr.value?.code ?? 'other'}`;
  return t(te(key) ? key : 'settings.backup.import.errors.other');
});

const errorDetail = computed(() => {
  const key = `settings.backup.import.errors.${importErr.value?.code ?? 'other'}_detail`;
  return t(te(key) ? key : 'settings.backup.import.errors.other_detail', {
    message: importErr.value?.message ?? '',
    name: fileName(importPath.value),
    path: importPath.value,
  });
});

function fail(e: unknown) {
  importErr.value = {
    code: e instanceof ApiError ? e.code : 'other',
    message: e instanceof Error ? e.message : String(e),
  };

  phase.value = 'error';
}

async function chooseBundle() {
  if (desktop) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');

      const picked = await open({
        multiple: false,
        directory: false,
        filters: [{ name: 'Curio bundle', extensions: ['curio', 'zip'] }],
      });

      if (typeof picked !== 'string') return;
      importPath.value = picked;
    } catch (e) {
      fail(e);
      return;
    }
  }
  if (importPath.value) await inspect();
}

async function inspect() {
  if (!importPath.value) return;
  phase.value = 'reading';
  importErr.value = null;
  info.value = null;
  result.value = null;
  showDamaged.value = false;
  try {
    const got = await api.post<BundleInspect>('/api/bundle/inspect', { path: importPath.value });
    mode.value = 'merge';
    settings.value = 'keep';
    takeSecrets.value = false;
    salvage.value = true;
    policies.value = Object.fromEntries(got.conflicts.map((c) => [c.slug, 'merge' as WatchPolicy]));
    info.value = got;
    phase.value = 'idle';
    await jobs.loadPipeline();
    await jobs.load();
    await nextTick();
    cancelBtn.value?.focus();
  } catch (e) {
    fail(e);
  }
}

// ---- import: the sheet -----------------------------------------------------------
const mode = ref<'merge' | 'restore'>('merge');
const settings = ref<'keep' | 'take'>('keep');
const takeSecrets = ref(false);
const salvage = ref(true);
const policies = ref<Record<string, WatchPolicy>>({});
const importing = ref(false);
const cancelBtn = ref<HTMLButtonElement | null>(null);

const POLICIES: WatchPolicy[] = ['merge', 'keep', 'take'];

/** a restore takes the bundle's settings, cookie included when there is one */
watch(mode, (m) => {
  if (m === 'restore') {
    settings.value = 'take';
    takeSecrets.value = !!info.value?.has.secrets;
  }
});

/** the daemon's gate, mirrored so the button says why it is off */
const gateOpen = computed(
  () => !!jobs.pipeline?.paused && jobs.running.length === 0 && jobs.queued.length === 0,
);

const conflictOf = (slug: string) => info.value?.conflicts.find((c) => c.slug === slug) ?? null;

async function pausePipeline() {
  await jobs.pauseQueue(true);
  await jobs.load();
}

function closeSheet() {
  if (!importing.value) info.value = null;
}

async function runImport() {
  if (!info.value || !gateOpen.value) return;
  importing.value = true;
  const name = fileName(info.value.path);

  const body: BundleImportBody = {
    path: info.value.path,
    mode: mode.value,
    settings: mode.value === 'restore' ? 'take' : settings.value,
    secrets: takeSecrets.value && info.value.has.secrets,
    characters: mode.value === 'merge' ? policies.value : {},
    salvage: salvage.value,
  };

  try {
    const r = await api.post<BundleImportResult>('/api/bundle/import', body);
    result.value = r;
    resultMeta.value = { name, mode: body.mode };
    info.value = null;
    phase.value = 'result';
    await Promise.all([lib.loadWatches(), ep.refresh()]);
    if (r.ui && Object.keys(r.ui).length) {
      applyUiState(r.ui);
      reloading.value = true;
      setTimeout(() => window.location.reload(), 2000);
    }
  } catch (e) {
    info.value = null;
    fail(e);
  } finally {
    importing.value = false;
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && info.value && !importing.value) {
    e.preventDefault();
    info.value = null;
  }
}

onMounted(() => window.addEventListener('keydown', onKey, true));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <div class="panel">
    <div class="phead">
      <span class="ptitle">{{ $t('settings.backup.title') }}</span>
      <span class="data text-small text-dim">{{ $t('settings.backup.sub') }}</span>
      <div class="spacer" />
      <span v-if="!desktop" class="data text-small text-dim">{{ $t('settings.backup.browserTag') }}</span>
    </div>

    <div class="plates">
      <!-- EXPORT -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="download" :size="13" />
          <b>{{ $t('settings.backup.export.title') }}</b>
        </div>
        <div class="grp" :class="{ faded: exporting }">
          <b>{{ $t('settings.backup.export.format') }}</b>
          <label class="opt">
            <input v-model="fmt" type="radio" value="curio" name="bundle-format" :disabled="exporting" />
            <span>
              <i class="t mono">.curio</i>
              <em class="d">{{ $t('settings.backup.export.curioHint') }}</em>
            </span>
          </label>
          <label class="opt">
            <input v-model="fmt" type="radio" value="zip" name="bundle-format" :disabled="exporting" />
            <span>
              <i class="t mono">.zip</i>
              <em class="d">{{ $t('settings.backup.export.zipHint') }}</em>
            </span>
          </label>
        </div>
        <div class="grp" :class="{ faded: exporting }">
          <b>{{ $t('settings.backup.export.include') }}</b>
          <label class="opt">
            <CheckboxRoot
              :model-value="images"
              :disabled="exporting"
              class="rk-checkbox"
              @update:model-value="(v) => (images = v === true)"
            />
            <span>
              <i class="t">{{ $t('settings.backup.export.images') }}</i>
              <em class="d">{{ $t('settings.backup.export.imagesHint') }}</em>
            </span>
          </label>
          <label class="opt" :class="{ dis: !images }">
            <CheckboxRoot
              :model-value="images && thumbs"
              :disabled="exporting || !images"
              class="rk-checkbox"
              @update:model-value="(v) => (thumbs = v === true)"
            />
            <span>
              <i class="t">{{ $t('settings.backup.export.thumbs') }}</i>
            </span>
          </label>
          <label class="opt">
            <CheckboxRoot
              :model-value="secrets"
              :disabled="exporting"
              class="rk-checkbox"
              @update:model-value="(v) => (secrets = v === true)"
            />
            <span>
              <i class="t">{{ $t('settings.backup.export.secrets') }}</i>
              <em class="d rose">
                <Icon name="warning" :size="11" />
                {{ $t('settings.backup.export.secretsHint') }}
              </em>
            </span>
          </label>
        </div>
        <div class="act">
          <button class="btn pri" :disabled="exporting" @click="runExport">
            {{ desktop ? $t('settings.backup.export.button') : $t('settings.backup.export.buttonBrowser') }}
          </button>
          <span v-if="!exportJob" class="data text-small text-dim">
            {{
              desktop ? $t('settings.backup.export.opensDialog') : $t('settings.backup.export.browserHint')
            }}
          </span>
          <span v-if="exportError" class="data text-small text-rose">{{ exportError }}</span>
        </div>

        <!-- the job block: running, then a receipt -->
        <div v-if="exportJob" class="job">
          <div v-if="exporting" class="top">
            <Icon name="loader" :size="13" class="text-ember" />
            <span class="data text-small text-tx">
              {{
                exportJob.state === 'queued'
                  ? $t('settings.backup.export.queued', { path: exportPath })
                  : $t('settings.backup.export.exporting', { path: exportPath })
              }}
            </span>
            <span v-if="runningStage" class="data text-small text-mut ml-auto">
              {{
                $t('settings.backup.export.stageCount', {
                  stage: runningStage.label,
                  done: runningStage.done,
                  total: runningStage.total ?? '?',
                })
              }}
            </span>
            <button
              class="btn sm"
              :class="{ 'ml-auto': !runningStage }"
              @click="exportJobId && jobs.cancel(exportJobId)"
            >
              {{ $t('settings.backup.export.cancel') }}
            </button>
          </div>
          <div v-else-if="exportJob.state === 'succeeded'" class="res ok">
            <Icon name="success" :size="13" />
            <div>
              <span class="k">{{ $t('settings.backup.export.exported') }}</span>
              · {{ exportPath }}
              <br />
              {{
                $t('settings.backup.export.doneSize', {
                  size: fm.bytes(exportJob.counters.bytes ?? 0),
                  images: exportJob.counters.images ?? 0,
                  characters: exportJob.counters.characters ?? 0,
                })
              }}
            </div>
            <button v-if="desktop" class="btn sm ml-auto" @click="reveal">
              {{ $t('settings.backup.export.reveal') }}
            </button>
            <button v-else class="btn sm ml-auto" @click="copyPath">
              {{ copied ? $t('settings.backup.export.copied') : $t('settings.backup.export.copyPath') }}
            </button>
          </div>
          <div v-else class="res bad">
            <Icon name="error" :size="13" />
            <div>
              {{
                exportJob.state === 'cancelled'
                  ? $t('settings.backup.export.cancelled')
                  : $t('settings.backup.export.failed', { error: exportJob.error ?? exportJob.state })
              }}
              <br />
              {{ $t('settings.backup.export.partRemoved', { path: exportPath }) }}
            </div>
            <button class="btn sm ml-auto text-tx" @click="retryExport">
              {{ $t('settings.backup.export.retry') }}
            </button>
          </div>
          <div class="stages" :class="{ receipt: !exporting }">
            <div v-for="s in stages" :key="s.name" class="st" :class="s.state">
              <s>{{ s.label }}</s>
              <u>{{ s.done }} / {{ s.total ?? '?' }}</u>
              <i><b :style="{ width: s.pct + '%' }" /></i>
            </div>
          </div>
        </div>
      </section>

      <!-- IMPORT -->
      <section class="plate cut">
        <div class="plh">
          <Icon name="upload" :size="13" />
          <b>{{ $t('settings.backup.import.title') }}</b>
          <div class="spacer" />
          <span v-if="resultMeta" class="data text-small text-mut">
            {{ $t('settings.backup.import.plateMeta', { name: resultMeta.name, mode: resultMeta.mode }) }}
          </span>
        </div>

        <!-- reading -->
        <div v-if="phase === 'reading'" class="res">
          <Icon name="loader" :size="13" class="text-ember" />
          <div>
            {{ $t('settings.backup.import.reading') }}
            <br />
            {{ importPath }}
          </div>
        </div>

        <!-- a file that could not be read -->
        <div v-else-if="phase === 'error' && importErr" class="err" :class="errorKind">
          <Icon :name="ERROR_ICON[errorKind]" :size="13" />
          <div>
            <b>{{ errorTitle }}</b>
            <u>{{ errorDetail }}</u>
          </div>
          <button v-if="importErr.code === 'bundle_too_new'" class="btn sm ml-auto" @click="emit('updates')">
            {{ $t('settings.backup.import.errors.updateFirst') }}
          </button>
          <button
            v-else-if="importErr.code === 'no_file' && desktop"
            class="btn sm ml-auto"
            @click="chooseBundle"
          >
            {{ $t('settings.backup.import.chooseAgain') }}
          </button>
        </div>

        <!-- after an import -->
        <div v-else-if="phase === 'result' && result" class="job">
          <div class="res ok">
            <Icon name="success" :size="13" />
            <div>
              <span class="k">{{ $t('settings.backup.import.done') }}</span>
              {{ $t('settings.backup.import.result', result) }}
            </div>
          </div>
          <div v-if="result.damaged.length" class="res bad">
            <Icon name="warning" :size="13" />
            <div>
              {{
                $t('settings.backup.import.damagedNote', { n: result.damaged.length }, result.damaged.length)
              }}
              <ul v-if="showDamaged" class="damaged">
                <li v-for="d in result.damaged" :key="d">{{ d }}</li>
              </ul>
            </div>
            <button class="btn sm ml-auto text-tx" @click="showDamaged = !showDamaged">
              {{ $t('settings.backup.import.which') }}
            </button>
          </div>
          <div v-if="reloading" class="res">
            <Icon name="refresh" :size="13" class="text-mut" />
            <div>{{ $t('settings.backup.import.reloading') }}</div>
          </div>
        </div>

        <!-- idle: the lead line -->
        <div v-else-if="desktop" class="data text-small text-dim">
          {{ $t('settings.backup.import.lead') }}
        </div>

        <div class="act" :class="{ 'mt-auto': phase === 'result' }">
          <template v-if="desktop">
            <button class="btn" :disabled="exporting || phase === 'reading'" @click="chooseBundle">
              {{ $t('settings.backup.import.choose') }}
            </button>
            <span class="data text-small text-dim">
              {{
                exporting ? $t('settings.backup.import.notWhileExport') : $t('settings.backup.import.kinds')
              }}
            </span>
          </template>
          <template v-else>
            <input
              v-model="importPath"
              class="inp data"
              :placeholder="$t('settings.backup.import.pathPlaceholder')"
              :disabled="exporting"
              @keydown.enter="inspect"
            />
            <button class="btn" :disabled="exporting || phase === 'reading' || !importPath" @click="inspect">
              {{ $t('settings.backup.import.inspect') }}
            </button>
          </template>
        </div>
        <div v-if="!desktop" class="data text-small text-dim">
          {{
            exporting ? $t('settings.backup.import.notWhileExport') : $t('settings.backup.import.pathHint')
          }}
        </div>
      </section>
    </div>
  </div>

  <!-- the import sheet -->
  <template v-if="info">
    <div class="scrim" @click="closeSheet" />
    <div class="sheet" role="dialog" aria-modal="true" :aria-label="$t('settings.backup.sheet.title')">
      <div class="hd">
        <h2>
          {{ $t('settings.backup.sheet.title') }}
          <span>{{ fileName(info.path) }}</span>
        </h2>
        <div class="data text-small text-mut">
          {{
            $t('settings.backup.sheet.meta', {
              format: '.' + info.format,
              version: info.app_version,
              schema: info.schema_version,
              date: fm.date(info.created_at, true),
            })
          }}
        </div>
        <div class="data text-base">{{ $t('settings.backup.sheet.counts', info.counts) }}</div>
        <button
          v-if="!importing"
          class="x"
          :aria-label="$t('settings.backup.sheet.close')"
          @click="closeSheet"
        >
          <Icon name="close" :size="13" />
        </button>
      </div>
      <div class="bd">
        <div v-if="!info.has.images" class="warn">
          <Icon name="warning" :size="13" />
          <span>{{ $t('settings.backup.sheet.noImages') }}</span>
        </div>

        <div class="grp">
          <b>{{ $t('settings.backup.sheet.mode') }}</b>
          <div class="modes">
            <label class="mode" :class="{ on: mode === 'merge' }">
              <input v-model="mode" type="radio" value="merge" name="bundle-mode" :disabled="importing" />
              <span>
                <i class="t">{{ $t('settings.backup.sheet.merge') }}</i>
                <em class="d">{{ $t('settings.backup.sheet.mergeHint') }}</em>
              </span>
            </label>
            <label class="mode rose" :class="{ on: mode === 'restore' }">
              <input v-model="mode" type="radio" value="restore" name="bundle-mode" :disabled="importing" />
              <span>
                <i class="t">{{ $t('settings.backup.sheet.restore') }}</i>
                <em class="d">{{ $t('settings.backup.sheet.restoreHint') }}</em>
              </span>
            </label>
          </div>
        </div>

        <div class="grp" :class="{ inert: mode === 'restore' }">
          <b>
            {{
              mode === 'restore'
                ? $t('settings.backup.sheet.settingsRestore')
                : $t('settings.backup.sheet.settings')
            }}
          </b>
          <div class="inline">
            <label class="opt">
              <input
                v-model="settings"
                type="radio"
                value="keep"
                name="bundle-settings"
                :disabled="mode === 'restore' || importing"
              />
              <span>
                <i class="t">{{ $t('settings.backup.sheet.keep') }}</i>
              </span>
            </label>
            <label class="opt">
              <input
                v-model="settings"
                type="radio"
                value="take"
                name="bundle-settings"
                :disabled="mode === 'restore' || importing"
              />
              <span>
                <i class="t">{{ $t('settings.backup.sheet.take') }}</i>
                <em class="d">{{ $t('settings.backup.sheet.takeHint') }}</em>
              </span>
            </label>
          </div>
          <label v-if="info.has.secrets" class="opt">
            <CheckboxRoot
              :model-value="takeSecrets"
              :disabled="mode === 'restore' || importing"
              class="rk-checkbox"
              @update:model-value="(v) => (takeSecrets = v === true)"
            />
            <span>
              <i class="t">{{ $t('settings.backup.sheet.secrets') }}</i>
            </span>
          </label>
        </div>

        <div class="grp">
          <b>{{ $t('settings.backup.sheet.characters', { n: info.characters.length }) }}</b>
          <ul class="chars">
            <li v-for="c in info.characters" :key="c.slug" class="cr">
              <div class="who">
                <div class="nm">{{ c.label || c.slug }}</div>
                <div class="tg" :title="c.pixiv_tags.join(' · ')">{{ c.pixiv_tags.join(' · ') }}</div>
              </div>
              <div class="pc">{{ $t('settings.backup.sheet.postCount', { n: c.posts }, c.posts) }}</div>
              <div class="stc">
                <span v-if="conflictOf(c.slug)?.kind === 'same_tags'" class="tag bad">
                  {{ $t('settings.backup.sheet.sameTags', { slug: conflictOf(c.slug)?.suggest ?? '' }) }}
                </span>
                <span v-else-if="c.new" class="tag new">{{ $t('settings.backup.sheet.new') }}</span>
                <span v-else-if="mode === 'restore'" class="tag">
                  {{ $t('settings.backup.sheet.replaced') }}
                </span>
                <select
                  v-else-if="conflictOf(c.slug)"
                  v-model="policies[c.slug]"
                  class="policy data"
                  :aria-label="c.label || c.slug"
                  :disabled="importing"
                >
                  <option v-for="p in POLICIES" :key="p" :value="p">
                    {{ $t(`settings.backup.sheet.policy.${p}`) }}
                  </option>
                </select>
                <span v-else class="tag ok">{{ $t('settings.backup.sheet.same') }}</span>
              </div>
            </li>
          </ul>
        </div>

        <label class="opt">
          <CheckboxRoot
            :model-value="salvage"
            :disabled="importing"
            class="rk-checkbox"
            @update:model-value="(v) => (salvage = v === true)"
          />
          <span>
            <i class="t">{{ $t('settings.backup.sheet.salvage') }}</i>
            <em class="d">{{ $t('settings.backup.sheet.salvageHint') }}</em>
          </span>
        </label>

        <div class="gate" :class="{ ok: gateOpen }">
          <Icon :name="gateOpen ? 'success' : 'pause'" :size="13" />
          <span>{{ gateOpen ? $t('settings.backup.sheet.gateOk') : $t('settings.backup.sheet.gate') }}</span>
          <button v-if="!gateOpen" class="btn sm ml-auto" @click="pausePipeline">
            {{ $t('settings.backup.sheet.pauseNow') }}
          </button>
        </div>
      </div>
      <div class="ft">
        <template v-if="importing">
          <Icon name="loader" :size="13" class="text-ember" />
          <span class="data text-small text-tx">{{ $t('settings.backup.sheet.importing') }}</span>
        </template>
        <span v-else class="data text-small text-dim">{{ $t('settings.backup.sheet.esc') }}</span>
        <div class="spacer" />
        <button ref="cancelBtn" class="btn" :disabled="importing" @click="closeSheet">
          {{ $t('settings.backup.sheet.cancel') }}
        </button>
        <button class="btn pri" :disabled="!gateOpen || importing" @click="runImport">
          {{ $t('settings.backup.sheet.run') }}
        </button>
      </div>
    </div>
  </template>
</template>

<style scoped>
.panel {
  container-type: inline-size;
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
.plate {
  background: var(--color-surf2);
  border: 1px solid var(--color-line-soft);
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}
.plh {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 25px;
  color: var(--color-mut);
}
.plh b,
.grp > b {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--color-dim);
}
.grp {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.grp.faded {
  opacity: 0.5;
}
.grp.inert {
  opacity: 0.4;
  pointer-events: none;
}
.inline {
  display: flex;
  gap: 25px;
  flex-wrap: wrap;
}
.opt {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  min-width: 0;
  cursor: pointer;
}
.opt.dis {
  opacity: 0.4;
}
.opt > input,
.opt > .rk-checkbox,
.mode > input {
  margin-top: 3px;
}
.opt > span,
.mode > span {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.t {
  font-style: normal;
  font-size: 14px;
  line-height: 20px;
  color: var(--color-tx);
}
.t.mono {
  font-family: var(--font-mono);
}
.d {
  font-style: normal;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-mut);
}
.d.rose {
  color: var(--color-rose);
  display: flex;
  gap: 6px;
  align-items: center;
}
.act {
  display: flex;
  align-items: center;
  gap: 15px;
  flex-wrap: wrap;
}
.mt-auto {
  margin-top: auto;
}
.ml-auto {
  margin-left: auto;
}
.inp {
  flex: 1;
  min-width: 200px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--color-line);
  background: var(--color-surf);
  font-size: 12px;
  color: var(--color-tx);
}
.inp::placeholder {
  color: var(--color-dim);
}
/* the job block and the result lines */
.job {
  border: 1px solid var(--color-line-soft);
  background: var(--color-surf);
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.top {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 25px;
}
.stages {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.stages.receipt {
  opacity: 0.6;
}
.st {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.st s {
  text-decoration: none;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--color-dim);
}
.st u {
  text-decoration: none;
  font: 12px var(--font-mono);
  color: var(--color-dim);
}
.st i {
  display: block;
  height: 3px;
  background: var(--color-line-soft);
}
.st i b {
  display: block;
  height: 100%;
  background: var(--color-ember);
}
.st.done s,
.st.done u {
  color: var(--color-moss);
}
.st.done i b {
  background: var(--color-moss);
}
.st.run s {
  color: var(--color-ember);
}
.st.run u {
  color: var(--color-tx);
}
.st.failed s,
.st.failed u {
  color: var(--color-rose);
}
.st.failed i b {
  background: var(--color-rose);
}
.res {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font: 12px/1.5 var(--font-mono);
  color: var(--color-mut);
}
.res > svg {
  margin-top: 2px;
  flex: none;
}
.res.ok > svg {
  color: var(--color-moss);
}
.res.ok .k {
  color: var(--color-tx);
}
.res.bad {
  color: var(--color-rose);
}
.res.bad > svg {
  color: var(--color-rose);
}
.res .btn {
  align-self: center;
  flex: none;
}
.damaged {
  list-style: none;
  margin: 5px 0 0;
  padding: 0;
  max-height: 120px;
  overflow: auto;
  color: var(--color-mut);
}
/* error cards */
.err {
  border: 1px solid var(--color-line);
  background: var(--color-surf);
  padding: 12px 15px;
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.err > svg {
  margin-top: 3px;
  flex: none;
  color: var(--color-mut);
}
.err b {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-tx);
}
.err u {
  text-decoration: none;
  display: block;
  font: 12px var(--font-mono);
  color: var(--color-mut);
  margin-top: 3px;
  word-break: break-all;
}
.err .btn {
  align-self: center;
  flex: none;
}
.err.rose {
  border-color: var(--color-rose);
}
.err.rose > svg,
.err.rose b {
  color: var(--color-rose);
}
.err.fill {
  border-color: var(--color-rose);
  background: color-mix(in srgb, var(--color-rose) 10%, var(--color-surf));
}
.err.fill > svg,
.err.fill b {
  color: var(--color-rose);
}
.err.dim {
  border-color: var(--color-line-soft);
}
.err.dim b {
  color: var(--color-mut);
}
.err.dim > svg {
  color: var(--color-dim);
}
/* the sheet */
.scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: color-mix(in srgb, var(--color-rail) 62%, transparent);
}
.sheet {
  --cut: 10px;
  position: fixed;
  z-index: 41;
  left: 50%;
  top: 5vh;
  transform: translateX(-50%);
  width: min(640px, 94vw);
  max-height: 90vh;
  background: var(--color-surf);
  border: 1px solid var(--color-line);
  display: flex;
  flex-direction: column;
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.hd {
  flex: none;
  position: relative;
  padding: 20px 20px 15px;
  border-bottom: 1px solid var(--color-line-soft);
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.hd::before {
  content: '';
  position: absolute;
  left: 0;
  top: 24px;
  width: 3px;
  height: 14px;
  background: var(--color-ember);
}
.hd h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
  padding-right: 30px;
}
.hd h2 span {
  font: 500 18px var(--font-mono);
  text-transform: none;
  letter-spacing: 0;
  color: var(--color-tx);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.x {
  position: absolute;
  right: 15px;
  top: 18px;
  width: 25px;
  height: 25px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-mut);
  background: none;
  border: 1px solid transparent;
  cursor: pointer;
}
.x:hover {
  color: var(--color-tx);
  border-color: var(--color-line);
}
.bd {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.ft {
  flex: none;
  padding: 15px 20px;
  border-top: 1px solid var(--color-line-soft);
  display: flex;
  align-items: center;
  gap: 10px;
}
.warn {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px;
  border: 1px solid var(--color-line);
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-tx);
}
.warn > svg {
  color: var(--color-mut);
  margin-top: 2px;
  flex: none;
}
.modes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.mode {
  border: 1px solid var(--color-line-soft);
  background: var(--color-surf2);
  padding: 10px 12px;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.mode.on {
  border-color: var(--color-ember);
}
.mode.rose.on {
  border-color: var(--color-rose);
  background: color-mix(in srgb, var(--color-rose) 8%, var(--color-surf2));
}
.mode.rose.on .t {
  color: var(--color-rose);
}
.chars {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--color-line-soft);
  background: var(--color-surf2);
  max-height: 238px;
  overflow: auto;
}
.cr {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 70px 170px;
  gap: 10px;
  align-items: center;
  padding: 8px 12px;
  min-height: 52px;
  border-bottom: 1px solid var(--color-line-soft);
}
.cr:last-child {
  border-bottom: none;
}
.who {
  min-width: 0;
}
.nm {
  font-size: 14px;
  color: var(--color-tx);
}
.tg {
  font: 12px var(--font-mono);
  color: var(--color-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pc {
  font: 12px var(--font-mono);
  color: var(--color-mut);
  text-align: right;
}
.stc {
  display: flex;
  justify-content: flex-end;
}
.tag {
  --cut: 5px;
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border: 1px solid var(--color-line);
  font: 500 10px var(--font-mono);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-mut);
  white-space: nowrap;
  clip-path: polygon(
    0 0,
    calc(100% - var(--cut)) 0,
    100% var(--cut),
    100% 100%,
    var(--cut) 100%,
    0 calc(100% - var(--cut))
  );
}
.tag.ok {
  border-color: var(--color-moss);
  color: var(--color-moss);
}
.tag.new {
  border-color: var(--color-ember);
  color: var(--color-ember);
}
.tag.bad {
  border-color: var(--color-rose);
  color: var(--color-rose);
  background: color-mix(in srgb, var(--color-rose) 10%, transparent);
}
.policy {
  height: 26px;
  padding: 0 8px 0 10px;
  border: 1px solid var(--color-line);
  background: var(--color-surf);
  font-size: 12px;
  color: var(--color-tx);
}
.policy:focus-visible {
  outline: none;
  border-color: var(--color-ember);
}
.gate {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--color-line);
  font-size: 12px;
  color: var(--color-tx);
}
.gate > svg {
  color: var(--color-mut);
  flex: none;
}
.gate.ok {
  border-color: var(--color-moss);
}
.gate.ok > svg,
.gate.ok span {
  color: var(--color-moss);
}
</style>
