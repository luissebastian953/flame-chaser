<script setup lang="ts">
import type { PurgePreview, PurgeScope, PurgeStatus } from '@/lib/types';

/**
 * Settings › Storage › Purge all data: one 520 px sheet, two steps, swapped
 * in place. Step 1 chooses the scope (galleries only, preselected; or
 * configs and galleries) with the live counts from GET
 * /api/storage/purge/preview. Step 2 asks for the phrase typed exactly,
 * trimmed and case-sensitive; the daemon checks it again. While the purge
 * runs, the footer counts images and nothing closes the sheet. A failure
 * keeps the sheet open with the daemon's error verbatim and offers Retry.
 *
 * Galleries only emits `done` with the outcome; the parent refreshes.
 * Configs and galleries clears the webview's own `curio.*` keys and reloads,
 * so the app comes back as freshly installed.
 */
const emit = defineEmits<{ close: []; done: [result: NonNullable<PurgeStatus['result']>] }>();
const { t } = useI18n();
const fm = useFormats();

/** the confirm phrase; data, never translated */
const PHRASE = 'PLEASE DELETE';
const POLL_MS = 250;

type Step = 'choose' | 'confirm' | 'running' | 'error';

const step = ref<Step>('choose');
const scope = ref<PurgeScope>('galleries');
const text = ref('');
const preview = ref<PurgePreview | null>(null);
const progress = reactive({ done: 0, total: 0 });
const error = ref('');

const cancelBtn = ref<HTMLButtonElement | null>(null);
const input = ref<HTMLInputElement | null>(null);

const matches = computed(() => text.value.trim() === PHRASE);
const canYes = computed(() => matches.value && (step.value === 'confirm' || step.value === 'error'));
const running = computed(() => step.value === 'running');

onMounted(async () => {
  text.value = '';
  await nextTick();
  cancelBtn.value?.focus();
  try {
    preview.value = await api.get<PurgePreview>('/api/storage/purge/preview');
  } catch {
    /* the counts stay "…"; the purge itself still works */
  }
});

const countLine = (s: PurgeScope) => {
  const p = preview.value;
  if (!p) return t('settings.purge.pending');
  const args = { images: fm.number(p.images), characters: fm.number(p.characters), size: fm.bytes(p.bytes) };
  return t(`settings.purge.${s}.count`, args);
};

const meta = computed(() => `${t(`settings.purge.${scope.value}.label`)} · ${countLine(scope.value)}`);

function close() {
  if (!running.value) emit('close');
}

async function toConfirm() {
  step.value = 'confirm';
  await nextTick();
  input.value?.focus();
}

let timer: ReturnType<typeof setTimeout> | null = null;

async function yes() {
  if (!canYes.value) return;
  step.value = 'running';
  error.value = '';
  progress.done = 0;
  progress.total = preview.value?.images ?? 0;
  try {
    const { job_id } = await api.post<{ job_id: string }>('/api/storage/purge', {
      scope: scope.value,
      confirm: text.value,
    });

    await follow(job_id);
  } catch (e) {
    fail(e instanceof Error ? e.message : String(e));
  }
}

async function follow(id: string): Promise<void> {
  const st = await api.get<PurgeStatus>(`/api/storage/purge/${id}`);
  progress.done = st.done;
  progress.total = st.total;
  if (st.state === 'running') {
    await new Promise<void>((resolve) => (timer = setTimeout(resolve, POLL_MS)));
    return follow(id);
  }
  if (st.state === 'failed' || !st.result) return fail(st.error ?? '');
  if (st.scope === 'all') return firstRun();
  emit('done', st.result);
}

function fail(message: string) {
  error.value = message;
  step.value = 'error';
}

/** the webview's half of a fresh install: every key Curio keeps, then reload */
function firstRun() {
  try {
    for (const key of Object.keys(localStorage)) if (key.startsWith('curio.')) localStorage.removeItem(key);
  } catch {
    /* storage blocked: nothing kept there either */
  }
  window.location.reload();
}

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return;
  e.preventDefault();
  e.stopPropagation();
  close();
}

onMounted(() => window.addEventListener('keydown', onKey, true));

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey, true);
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <div class="scrim" @click="close" />
  <div class="sheet" role="dialog" aria-modal="true" :aria-label="$t('settings.purge.title')">
    <!-- step 1: choose the scope -->
    <template v-if="step === 'choose'">
      <div class="hd">
        <h2>{{ $t('settings.purge.title') }}</h2>
        <div class="data text-small text-mut">{{ $t('settings.purge.meta') }}</div>
        <button class="x" :aria-label="$t('settings.purge.close')" @click="close">
          <Icon name="close" :size="13" />
        </button>
      </div>
      <div class="bd">
        <div class="grp">
          <b>{{ $t('settings.purge.group') }}</b>
          <div class="modes">
            <label
              v-for="s in ['galleries', 'all'] as const"
              :key="s"
              class="mode"
              :class="{ on: scope === s }"
            >
              <input v-model="scope" type="radio" :value="s" name="purge-scope" />
              <span>
                <i class="t">{{ $t(`settings.purge.${s}.title`) }}</i>
                <em class="d">{{ $t(`settings.purge.${s}.desc`) }}</em>
                <em class="c">{{ countLine(s) }}</em>
              </span>
            </label>
          </div>
        </div>
      </div>
      <div class="ft">
        <span class="data text-small text-dim">{{ $t('settings.purge.esc') }}</span>
        <div class="spacer" />
        <button ref="cancelBtn" class="btn" @click="close">{{ $t('settings.purge.cancel') }}</button>
        <button class="btn danger" @click="toConfirm">{{ $t('settings.purge.confirm') }}</button>
      </div>
    </template>

    <!-- step 2: type to confirm, then running / error in place -->
    <template v-else>
      <div class="hd">
        <h2 class="text-rose">{{ $t('settings.purge.sure') }}</h2>
        <div class="data text-small text-mut">{{ meta }}</div>
        <button v-if="!running" class="x" :aria-label="$t('settings.purge.close')" @click="close">
          <Icon name="close" :size="13" />
        </button>
      </div>
      <div class="bd" :class="{ inert: running }">
        <div class="err">
          <Icon name="warning" :size="13" />
          <span>
            <i class="t">{{ $t('settings.purge.warnTitle') }}</i>
            <em class="d">{{ $t('settings.purge.warnDetail') }}</em>
          </span>
        </div>
        <div class="grp">
          <i18n-t keypath="settings.purge.prompt" tag="b" scope="global">
            <template #phrase>
              <span class="phrase">{{ PHRASE }}</span>
            </template>
          </i18n-t>
          <input
            ref="input"
            v-model="text"
            class="phr"
            :class="{ ok: matches }"
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            :placeholder="PHRASE"
            :disabled="running"
            @keydown.enter.prevent="yes"
          />
        </div>
      </div>
      <div class="ft">
        <template v-if="running">
          <Icon name="loader" :size="13" class="spin text-rose" />
          <span class="data text-small text-tx">
            {{
              $t('settings.purge.running', {
                done: fm.number(progress.done),
                total: fm.number(progress.total),
              })
            }}
          </span>
        </template>
        <span v-else-if="step === 'error'" class="data text-small text-rose fail">
          {{ $t('settings.purge.failed', { error }) }}
        </span>
        <span v-else class="data text-small text-dim">{{ $t('settings.purge.escNo') }}</span>
        <div class="spacer" />
        <button class="btn" :disabled="running" @click="close">{{ $t('settings.purge.no') }}</button>
        <button class="btn yes" :disabled="!canYes" @click="yes">
          {{ step === 'error' ? $t('settings.purge.retry') : $t('settings.purge.yes') }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
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
  top: 10vh;
  transform: translateX(-50%);
  width: min(520px, 94vw);
  max-height: 80vh;
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
  padding-right: 30px;
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
.bd.inert {
  pointer-events: none;
  opacity: 0.6;
}
.ft {
  flex: none;
  padding: 15px 20px;
  border-top: 1px solid var(--color-line-soft);
  display: flex;
  align-items: center;
  gap: 10px;
}
.fail {
  min-width: 0;
  overflow-wrap: anywhere;
}
.grp {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.grp > b {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--color-dim);
}
.phrase {
  font-family: var(--font-mono);
  color: var(--color-tx);
  letter-spacing: 0.08em;
}
.modes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mode {
  border: 1px solid var(--color-line-soft);
  background: var(--color-surf2);
  padding: 12px;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.mode.on {
  border-color: var(--color-rose);
  background: color-mix(in srgb, var(--color-rose) 8%, var(--color-surf2));
}
.mode > input {
  margin-top: 3px;
  accent-color: var(--color-rose);
}
.mode > span,
.err > span {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.t {
  font-style: normal;
  font-size: 14px;
  color: var(--color-tx);
}
.d {
  font-style: normal;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-mut);
}
.c {
  font-style: normal;
  font: 12px var(--font-mono);
  color: var(--color-dim);
  margin-top: 5px;
}
.err {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid var(--color-rose);
  background: color-mix(in srgb, var(--color-rose) 10%, var(--color-surf));
  color: var(--color-rose);
}
.err > svg {
  flex: none;
  margin-top: 3px;
}
.err .t {
  color: var(--color-rose);
}
.err .d {
  font-family: var(--font-mono);
}
.phr {
  height: 30px;
  padding: 0 10px;
  background: var(--color-surf);
  border: 1px solid var(--color-line);
  color: var(--color-tx);
  font: 12px var(--font-mono);
  letter-spacing: 0.06em;
  outline: none;
}
.phr::placeholder {
  color: var(--color-dim);
}
.phr:focus {
  border-color: var(--color-ember);
}
.phr.ok,
.phr.ok:focus {
  border-color: var(--color-rose);
}
.btn.yes {
  background: var(--color-rose);
  border-color: var(--color-rose);
  color: var(--color-bg);
  font-weight: 600;
}
.btn.yes:hover:not(:disabled) {
  filter: brightness(1.08);
}
.btn.yes:disabled,
.btn.yes:disabled:hover {
  background: var(--color-rose);
  border-color: var(--color-rose);
  color: var(--color-bg);
  opacity: 0.35;
}
</style>
