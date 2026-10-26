<script setup lang="ts">
/**
 * Smart · AI identifier: the criteria panel on the left of the grid. Each
 * criterion has a checkbox, a title and its live count in rose; the counts
 * come from the daemon 150 ms after the last change (stores/deletion.ts).
 * The footer offers to keep the same criteria at crawl time, which writes
 * them to Settings › Duplicates.
 */
const props = defineProps<{ slug: string }>();
const del = useDeletion();
const fm = useFormats();
const { t } = useI18n();
const applying = ref(false);
const applied = computed(() => !!del.smartResult?.rule);

const counts = computed(
  () => del.smartResult?.counts ?? { score: 0, other: 0, dupe: 0, unidentified: 0, kind: 0 },
);

const cutoff = computed(() => del.smartResult?.cutoff ?? 0.5);
const scoreOn = computed(() => del.smart.minScore !== null);
const score = computed(() => del.smart.minScore ?? Math.max(0, cutoff.value - SCORE_UNDER_CUTOFF));

const otherLabel = computed(() =>
  del.smartResult?.primary_label
    ? t('gallery.delete.smart.other', { label: del.smartResult.primary_label })
    : t('gallery.delete.smart.otherUnknown'),
);

function toggleScore(on: boolean) {
  del.setSmart({ minScore: on ? score.value : null });
}

function setScore(v: number[] | undefined) {
  del.setSmart({ minScore: v?.[0] ?? score.value });
}

async function applyAtCrawl(on: boolean) {
  applying.value = true;
  try {
    await api.put('/api/config', {
      cleanup_rule: { active: on, min_score: del.smart.minScore, other_character: del.smart.other },
    });

    await del.loadSmart();
  } finally {
    applying.value = false;
  }
}

// counts on entry, and again when the character changes under the panel
watch(
  () => props.slug,
  () => void del.loadSmart(),
  { immediate: true },
);
</script>

<template>
  <aside class="smart">
    <div class="head">
      <span class="ptitle">{{ $t('gallery.delete.smart.title') }}</span>
      <span v-if="del.smartLoading" class="mono dim">
        <Icon name="loader" class="spin" :size="11" />
        {{ $t('gallery.delete.smart.loading') }}
      </span>
    </div>
    <div v-if="del.smartResult && !del.smartResult.identifier.enabled" class="hint off">
      {{ $t('gallery.delete.smart.off') }}
    </div>

    <!-- low recognition score -->
    <label class="crit">
      <CheckboxRoot
        :model-value="scoreOn"
        class="rk-checkbox"
        @update:model-value="(v) => toggleScore(v === true)"
      />
      <span class="ttl">{{ $t('gallery.delete.smart.score') }}</span>
      <b class="n">{{ fm.number(counts.score) }}</b>
    </label>
    <div class="sub">
      <span class="mono">{{ $t('gallery.delete.smart.scoreValue', { n: score.toFixed(2) }) }}</span>
      <SliderRoot
        :model-value="[score]"
        :min="0"
        :max="1"
        :step="0.01"
        :disabled="!scoreOn"
        class="rk-slider"
        @update:model-value="setScore"
      >
        <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
        <SliderThumb class="rk-slider-thumb" :aria-label="$t('gallery.delete.smart.scoreAria')" />
      </SliderRoot>
      <span class="note">{{ $t('gallery.delete.smart.scoreNote', { n: cutoff.toFixed(2) }) }}</span>
    </div>

    <!-- not this character -->
    <label class="crit">
      <CheckboxRoot
        :model-value="del.smart.other"
        :disabled="!del.smartResult?.primary"
        class="rk-checkbox"
        @update:model-value="(v) => del.setSmart({ other: v === true })"
      />
      <span class="ttl">{{ otherLabel }}</span>
      <b class="n">{{ fm.number(counts.other) }}</b>
    </label>
    <div class="sub">
      <span class="note">{{ $t('gallery.delete.smart.otherNote') }}</span>
      <div v-if="del.smartResult?.characters.length" class="chips">
        <span v-for="c in del.smartResult.characters" :key="c.name" class="chip" :title="c.name">
          <Icon name="user" :size="11" />
          {{ c.label }}
          <em>{{ c.count }}</em>
        </span>
      </div>
    </div>

    <!-- near-duplicates -->
    <label class="crit">
      <CheckboxRoot
        :model-value="del.smart.dupes"
        class="rk-checkbox"
        @update:model-value="(v) => del.setSmart({ dupes: v === true })"
      />
      <span class="ttl">{{ $t('gallery.delete.smart.dupes') }}</span>
      <b class="n">{{ fm.number(counts.dupe) }}</b>
    </label>
    <div class="sub">
      <span class="mono">{{ $t('gallery.delete.smart.dupesValue', { n: del.smart.distance }) }}</span>
      <SliderRoot
        :model-value="[del.smart.distance]"
        :min="0"
        :max="16"
        :step="1"
        :disabled="!del.smart.dupes"
        class="rk-slider"
        @update:model-value="(v) => del.setSmart({ distance: v?.[0] ?? DEFAULT_DISTANCE })"
      >
        <SliderTrack class="rk-slider-track"><SliderRange class="rk-slider-range" /></SliderTrack>
        <SliderThumb class="rk-slider-thumb" :aria-label="$t('gallery.delete.smart.dupesAria')" />
      </SliderRoot>
      <span class="note">{{ $t('gallery.delete.smart.dupesNote') }}</span>
    </div>

    <!-- not an illustration: photos (cosplay, people, figures), 3D, screenshots -->
    <label class="crit">
      <CheckboxRoot
        :model-value="del.smart.kinds"
        class="rk-checkbox"
        @update:model-value="(v) => del.setSmart({ kinds: v === true })"
      />
      <span class="ttl">{{ $t('gallery.delete.smart.kinds') }}</span>
      <b class="n">{{ fm.number(counts.kind) }}</b>
    </label>
    <div class="sub">
      <span class="note">{{ $t('gallery.delete.smart.kindsNote') }}</span>
    </div>

    <!-- unidentified -->
    <label class="crit">
      <CheckboxRoot
        :model-value="del.smart.unidentified"
        class="rk-checkbox"
        @update:model-value="(v) => del.setSmart({ unidentified: v === true })"
      />
      <span class="ttl">{{ $t('gallery.delete.smart.unidentified') }}</span>
      <b class="n">{{ fm.number(counts.unidentified) }}</b>
    </label>
    <div class="sub">
      <span class="note">{{ $t('gallery.delete.smart.unidentifiedNote') }}</span>
    </div>

    <div class="foot">
      <div class="mono">
        {{ $t('gallery.delete.smart.matched', { n: fm.number(del.base.length) }) }}
        ·
        {{ $t('gallery.delete.smart.unchecked', { n: fm.number(del.dropped.length) }) }}
      </div>
      <label class="crit apply">
        <CheckboxRoot
          :model-value="applied"
          :disabled="applying"
          class="rk-checkbox"
          @update:model-value="(v) => applyAtCrawl(v === true)"
        />
        <span class="ttl">{{ $t('gallery.delete.smart.applyAtCrawl') }}</span>
        <span v-if="applied" class="chip on">{{ $t('gallery.delete.smart.applied') }}</span>
      </label>
      <span class="note">{{ $t('gallery.delete.smart.applyNote') }}</span>
    </div>
  </aside>
</template>

<style scoped>
.smart {
  flex: none;
  width: 300px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  background: color-mix(in oklch, var(--color-surf) 60%, transparent);
  border-right: 1px solid var(--color-line-soft);
  overflow: auto;
}
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 4px;
}
.mono {
  font: 11px var(--font-mono);
  color: var(--color-dim);
}
.dim {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.crit {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 8px;
  cursor: pointer;
}
.ttl {
  flex: 1;
  font-size: 12.5px;
  font-weight: 600;
}
.n {
  font: 600 12px var(--font-mono);
  color: var(--color-rose);
}
.sub {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 27px;
}
.note {
  font: 10.5px/1.4 var(--font-mono);
  color: var(--color-dim);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.chip em {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-dim);
}
.foot {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--color-line-soft);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.apply {
  margin-top: 4px;
}
.hint.off {
  font: 11px/1.4 var(--font-mono);
  color: oklch(0.8 0.15 75);
}
</style>
