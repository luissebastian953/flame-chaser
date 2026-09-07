<script setup lang="ts">
/**
 * Add / edit character. Everything on the right and in the footer comes from
 * POST /api/pixiv/probe -- one search page per tag, debounced here, cached in
 * the daemon. The slug is derived from the name and frozen after the first
 * save: folder names and post_watches rows key off it.
 */
import type { ProbeResult, Watch } from '@/lib/types';

const props = defineProps<{ watch: Watch; isNew: boolean }>();
const emit = defineEmits<{ save: [w: Watch, run: boolean]; close: [] }>();
const src = useSources();
const router = useRouter();
const { t } = useI18n();

/** Desktop: the login window. Browser mode: hand off to Settings › Accounts. */
function connect(source: 'pixiv' | 'twitter') {
  if (src.inTauri) void src.connectViaWindow(source);
  else {
    emit('close');
    void router.push('/settings');
  }
}

const w = reactive<Watch>({
  ...props.watch,
  pixiv_tags: [...props.watch.pixiv_tags],
  match_terms: [...props.watch.match_terms],
});

const newTag = ref('');
const newTerm = ref('');
const err = ref('');
const probe = ref<ProbeResult | null>(null);
const probing = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;

const slugify = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

const slugPreview = computed(() => w.slug || slugify(w.label) || '');

// ---- tags ------------------------------------------------------------------
const FULLWIDTH = /[（）]/;

function addTag() {
  const t = newTag.value.trim();
  if (t && !w.pixiv_tags.includes(t)) w.pixiv_tags.push(t);
  newTag.value = '';
}

function addTerm() {
  const t = newTerm.value.trim();
  if (t && !w.match_terms.includes(t)) w.match_terms.push(t);
  newTerm.value = '';
}

function addSuggested(raw: string) {
  if (!w.pixiv_tags.includes(raw)) w.pixiv_tags.push(raw);
}

const tagStatus = (t: string) => probe.value?.tags.find((p) => p.tag === t) ?? null;

// ---- probe (debounced) -----------------------------------------------------
async function runProbe() {
  if (src.status && !src.pixivOk) {
    probe.value = null;
    return;
  } // badge explains; no request spent
  const tags = w.pixiv_tags.filter((t) => !FULLWIDTH.test(t)).slice(0, 8);
  const fw = w.pixiv_tags.filter((t) => FULLWIDTH.test(t));
  if (!tags.length && !fw.length) {
    probe.value = null;
    return;
  }
  probing.value = true;
  try {
    const r = await api.post<ProbeResult>('/api/pixiv/probe', {
      tags: [...tags, ...fw],
      include_r18: w.include_r18,
    });

    probe.value = r;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    probing.value = false;
  }
}

watch(
  () => [w.pixiv_tags.join('\u0000'), w.include_r18],
  () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(runProbe, 350);
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
});

const suggestions = computed(() =>
  (probe.value?.suggestions ?? []).filter((s) => !w.pixiv_tags.includes(s.tag_raw)),
);

const estimate = computed(() => {
  const e = probe.value?.estimate;
  if (!e || !e.artworks) return null;
  const m = Math.round(e.seconds / 60);
  return {
    artworks: e.artworks,
    time:
      m < 1
        ? t('character.estimate.underMinute')
        : m < 90
          ? t('character.estimate.aboutMinutes', { m })
          : t('character.estimate.aboutHours', { h: (m / 60).toFixed(1) }),
  };
});

// ---- bookmarks slider (log-ish steps so 0..5000 is usable) -----------------
const STEPS = [0, 10, 25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000];

const stepIdx = computed({
  get: () => {
    const i = STEPS.findIndex((s) => s >= w.min_bookmarks);
    return [i < 0 ? STEPS.length - 1 : i];
  },
  set: (v) => {
    w.min_bookmarks = STEPS[v[0] ?? 0] ?? 0;
  },
});

// ---- submit ----------------------------------------------------------------
function validate(): boolean {
  err.value = '';
  if (!w.label.trim()) {
    err.value = t('character.errors.name');
    return false;
  }
  if (!w.slug) w.slug = slugify(w.label);
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(w.slug)) {
    err.value = t('character.errors.slug');
    return false;
  }
  if (!w.pixiv_tags.length) {
    err.value = t('character.errors.noTags');
    return false;
  }
  if (w.pixiv_tags.every((t) => FULLWIDTH.test(t))) {
    err.value = t('character.errors.allFullwidth');
    return false;
  }
  return true;
}

function submit(run: boolean) {
  if (validate()) emit('save', { ...w, pixiv_tags: [...w.pixiv_tags], match_terms: [...w.match_terms] }, run);
}
</script>

<template>
  <div class="scrim" @click.self="emit('close')">
    <div class="modal panel square">
      <div class="phead head">
        <div>
          <div class="text-medium font-semibold">
            {{ isNew ? $t('character.title.add') : $t('character.title.edit', { name: w.label || w.slug }) }}
          </div>
          <div class="data text-small text-dim">{{ $t('character.title.tagline') }}</div>
        </div>
        <div class="spacer" />
        <button class="btn gh sm" :aria-label="$t('character.close')" @click="emit('close')">✕</button>
      </div>

      <div class="cols">
        <!-- ============================== main column -->
        <div class="main-col">
          <div class="grid2">
            <div class="field">
              <label>
                {{ $t('character.name.label') }}
                <span class="hint">{{ $t('character.name.hint') }}</span>
              </label>
              <input v-model="w.label" :placeholder="$t('character.name.placeholder')" autofocus />
            </div>
            <div class="field">
              <label>
                {{ $t('character.slug.label') }}
                <span class="hint">
                  {{ isNew ? $t('character.slug.hintNew') : $t('character.slug.hintFrozen') }}
                </span>
              </label>
              <input
                :value="slugPreview"
                class="data text-small"
                disabled
                :placeholder="isNew ? $t('character.slug.placeholder') : ''"
              />
            </div>
          </div>

          <div class="sec">
            <div class="sec-h">
              <span class="n">1</span>
              <b>{{ $t('character.tags.heading') }}</b>
              <AuthBadge
                :state="src.pixivOk ? 'on' : src.status?.pixiv.verified === false ? 'expired' : 'off'"
                @connect="connect('pixiv')"
              />
            </div>
            <div class="hint">{{ $t('character.tags.hint') }}</div>
            <div class="rows">
              <div
                v-for="(tag, i) in w.pixiv_tags"
                :key="tag"
                class="row"
                :class="{ bad: tagStatus(tag)?.warning || tagStatus(tag)?.error }"
              >
                <input :value="tag" class="jp" readonly />
                <span class="stat">
                  <template v-if="!tagStatus(tag)">
                    <span class="text-dim data text-small">
                      {{ probing ? $t('character.tags.checking') : '' }}
                    </span>
                  </template>
                  <template v-else-if="tagStatus(tag)!.ok">
                    <span class="ok">
                      {{
                        $t(
                          'character.tags.artworks',
                          { n: tagStatus(tag)!.total.toLocaleString() },
                          tagStatus(tag)!.total,
                        )
                      }}
                    </span>
                  </template>
                  <template v-else-if="tagStatus(tag)!.error">
                    <span class="err">
                      {{ $t('character.tags.error', { error: tagStatus(tag)!.error }) }}
                    </span>
                  </template>
                  <template v-else>
                    <span class="err">
                      {{ $t('character.tags.warning', { warning: tagStatus(tag)!.warning }) }}
                    </span>
                  </template>
                </span>
                <button
                  class="btn gh sm"
                  :aria-label="$t('character.tags.remove')"
                  @click="w.pixiv_tags.splice(i, 1)"
                >
                  ✕
                </button>
              </div>
              <input
                v-model="newTag"
                class="jp add"
                :placeholder="$t('character.tags.placeholder')"
                @keydown.enter.prevent="addTag"
                @blur="addTag"
              />
            </div>
          </div>

          <div class="sec">
            <div class="sec-h">
              <span class="n">2</span>
              <b>{{ $t('character.terms.heading') }}</b>
              <AuthBadge :state="src.twitterOk ? 'on' : 'off'" @connect="connect('twitter')" />
            </div>
            <div class="hint">{{ $t('character.terms.hint') }}</div>
            <div class="chips">
              <span v-for="(term, i) in w.match_terms" :key="term" class="chip mono">
                {{ term }}
                <button
                  class="x"
                  :aria-label="$t('character.terms.remove')"
                  @click="w.match_terms.splice(i, 1)"
                >
                  ✕
                </button>
              </span>
              <input
                v-model="newTerm"
                class="term"
                :placeholder="$t('character.terms.placeholder')"
                @keydown.enter.prevent="addTerm"
                @blur="addTerm"
              />
            </div>
          </div>

          <div class="grid2 align-start">
            <div class="field">
              <label>
                {{ $t('character.bookmarks.label') }}
                <span class="hint">{{ $t('character.bookmarks.hint') }}</span>
              </label>
              <div class="flex items-center gap-15">
                <input v-model.number="w.min_bookmarks" type="number" min="0" class="data w-100 text-right" />
                <SliderRoot
                  v-model="stepIdx"
                  :min="0"
                  :max="STEPS.length - 1"
                  :step="1"
                  class="rk-slider flex-1"
                >
                  <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
                  <SliderThumb class="rk-slider-thumb" :aria-label="$t('character.bookmarks.slider')" />
                </SliderRoot>
              </div>
              <div class="hint">{{ $t('character.bookmarks.note') }}</div>
            </div>
            <div class="field">
              <label>
                {{ $t('character.r18.label') }}
                <span class="hint">{{ $t('character.r18.hint') }}</span>
              </label>
              <div class="flex items-center gap-10 h-30">
                <SwitchRoot id="r18" v-model="w.include_r18" class="rk-switch">
                  <SwitchThumb class="rk-switch-thumb" />
                </SwitchRoot>
                <label for="r18" class="text-small">
                  {{ w.include_r18 ? $t('character.r18.on') : $t('character.r18.off') }}
                </label>
              </div>
            </div>
          </div>

          <div v-if="probe?.preview.length" class="sec preview">
            <div class="sec-h">
              <b>{{ $t('character.preview.heading') }}</b>
              <span class="hint">{{ $t('character.preview.lead', { tag: w.pixiv_tags[0] }) }}</span>
            </div>
            <div class="strip">
              <div
                v-for="p in probe.preview"
                :key="p.illust_id"
                class="tile"
                :title="`${p.title} — ${p.artist_name}`"
              >
                <img v-if="p.thumb" :src="authedUrl(p.thumb)" loading="lazy" alt="" />
              </div>
            </div>
          </div>

          <div v-if="err" class="err">{{ err }}</div>
        </div>

        <!-- ============================== suggestions -->
        <aside class="side-col">
          <div class="ptitle">{{ $t('character.suggestions.heading') }}</div>
          <div class="hint">{{ $t('character.suggestions.lead') }}</div>
          <div v-if="suggestions.length" class="sug">
            <div v-for="s in suggestions" :key="s.tag_norm" class="sug-row" :class="{ low: s.score < 0.3 }">
              <span class="jp">{{ s.tag_raw }}</span>
              <span class="data text-small text-right">
                <span :class="s.score >= 0.3 ? 'text-ember' : 'text-dim'">{{ s.score.toFixed(2) }}</span>
                <br />
                <span class="text-dim">{{ Math.round(s.share * 100) }}%</span>
              </span>
              <button v-if="s.score >= 0.3" class="add" @click="addSuggested(s.tag_raw)">
                {{ $t('character.suggestions.add') }}
              </button>
              <span v-else class="text-dim">—</span>
            </div>
          </div>
          <div v-else class="hint mt-15">
            {{
              probing
                ? $t('character.suggestions.checking')
                : w.pixiv_tags.length
                  ? $t('character.suggestions.none')
                  : $t('character.suggestions.empty')
            }}
          </div>
          <div class="spacer" />
          <div class="hint">{{ $t('character.suggestions.refresh') }}</div>
        </aside>
      </div>

      <div class="foot">
        <i18n-t v-if="estimate" keypath="character.estimate.line" tag="span" class="data text-small text-dim">
          <template #n>
            <b class="text-tx">{{ estimate.artworks.toLocaleString() }}</b>
          </template>
          <template #time>
            <b class="text-tx">{{ estimate.time }}</b>
          </template>
        </i18n-t>
        <div class="spacer" />
        <button class="btn gh" @click="emit('close')">{{ $t('character.actions.cancel') }}</button>
        <button class="btn" @click="submit(false)">{{ $t('character.actions.saveOnly') }}</button>
        <button class="btn pri" @click="submit(true)">{{ $t('character.actions.saveRun') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: absolute;
  inset: 0;
  background: oklch(0 0 0 / 0.66);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 30;
}
.modal {
  width: min(1120px, 94%);
  max-height: 92%;
  display: flex;
  flex-direction: column;
  box-shadow: 0 32px 72px oklch(0 0 0 / 0.6);
}
.head {
  padding: 14px 20px;
}
.cols {
  display: grid;
  grid-template-columns: 1fr 300px;
  min-height: 0;
  overflow: auto;
}
.main-col {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  border-right: 1px solid var(--line-soft);
}
.side-col {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.align-start {
  align-items: start;
}
.sec {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sec-h {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.sec-h .n {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font: 600 11px var(--mono);
  color: var(--ember);
  border: 1px solid color-mix(in oklch, var(--ember) 45%, transparent);
  background: color-mix(in oklch, var(--ember) 15%, transparent);
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.row {
  display: grid;
  grid-template-columns: 1fr 220px auto;
  gap: 10px;
  align-items: center;
}
.row input[readonly] {
  background: var(--bg);
}
.row.bad input {
  border-color: color-mix(in oklch, var(--rose) 60%, transparent);
}
.stat {
  font-size: 12.5px;
}
.stat .ok {
  color: var(--moss);
}
.add {
  border-style: dashed;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.chips .term {
  width: 120px;
  height: 24px;
  padding: 0 9px;
  font-size: 12px;
}
.x {
  background: none;
  border: none;
  color: var(--dim);
  padding: 0 0 0 4px;
}
.strip {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}
.tile {
  aspect-ratio: 1;
  background: var(--surf2);
  overflow: hidden;
}
.tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.sug {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sug-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--line-soft);
  background: var(--surf2);
}
.sug-row.low {
  color: var(--dim);
  background: transparent;
}
.sug-row .add {
  background: none;
  border: 0;
  color: var(--moss);
  font: 600 12px var(--font);
  padding: 0;
}
.foot {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 13px 20px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg);
}
</style>
