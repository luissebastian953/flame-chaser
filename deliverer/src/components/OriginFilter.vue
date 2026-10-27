<script setup lang="ts">
/**
 * How this character's images were made (coreflame/origin.py): chips for
 * hand-drawn / AI-made / not judged yet, to narrow the grid. The label only
 * labels -- nothing is removed. Offers the `label` job for images stored
 * before the detector existed. Independent of the Who row: how an image was
 * made is not who is in it.
 */
import type { OriginState } from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const jobs = useJobs();
const del = useDeletion();
const { t } = useI18n();
// By tag (stores/deletion.ts): a chip marks the images in that state
const selecting = computed(() => del.mode === 'tag');
const total = computed(() => Object.values(counts.value).reduce((a, b) => a + b, 0));

const INSTALL = "pip install 'reaver[classify]'"; // data, shown verbatim

const jobId = ref<string | null>(null);
const job = computed(() => (jobId.value ? (jobs.jobs.find((j) => j.id === jobId.value) ?? null) : null));
const running = computed(() => !!job.value && ['queued', 'running'].includes(job.value.state));

const counts = computed(() => lib.origins?.counts ?? { ai: 0, human: 0, pending: 0 });
const pending = computed(() => counts.value.pending);
const detector = computed(() => lib.origins?.detector ?? null);
// "Not judged yet" only exists while something is
const states = computed(() => ORIGIN_STATES.filter((s) => s !== 'pending' || pending.value > 0));

function toggle(s: OriginState) {
  if (selecting.value) {
    void del.toggleTerm('origin', s, t(`gallery.made.state.${s}`), lib.gridQuery(props.slug), total.value);
    return;
  }
  const on = lib.made.includes(s);
  const next = on ? lib.made.filter((x) => x !== s) : [...lib.made, s];
  if (!next.some((x) => states.value.includes(x))) return; // never an empty grid by accident

  void lib.setMade(props.slug, next);
}

async function judgeNow() {
  jobId.value = await jobs.submit('label');
}

// the jobs store follows the daemon's events; when our job ends, recount and redraw
watch(
  () => job.value?.state,
  async (state) => {
    if (state && !['queued', 'running'].includes(state)) {
      await Promise.all([lib.loadOrigins(props.slug), lib.loadGrid(props.slug, true)]);
    }
  },
);
</script>

<template>
  <div class="made">
    <div class="row">
      <span class="ptitle">{{ $t('gallery.made.title') }}</span>
      <button
        v-for="s in states"
        :key="s"
        class="chip"
        :class="selecting ? { pick: true, sel: del.isTerm('origin', s) } : { on: lib.made.includes(s) }"
        :aria-pressed="selecting ? del.isTerm('origin', s) : lib.made.includes(s)"
        @click="toggle(s)"
      >
        <Icon v-if="selecting && del.isTerm('origin', s)" name="close" :size="10" />
        {{ $t(`gallery.made.state.${s}`) }}
        <em>{{ counts[s] }}</em>
      </button>
      <template v-if="pending > 0 && detector">
        <span v-if="!detector.available" class="hint">
          <Icon name="warning" :size="12" />
          {{ $t('gallery.made.unavailable', { cmd: INSTALL }) }}
        </span>
        <span v-else-if="running" class="hint data">
          <Icon name="loader" class="spin" :size="12" />
          {{
            job?.total
              ? $t('gallery.made.judging', { done: job.done, total: job.total })
              : $t('gallery.made.judgingStarting')
          }}
        </span>
        <template v-else>
          <button class="btn sm" @click="judgeNow">
            <Icon name="scan" :size="13" />
            {{ $t('gallery.made.judgeNow', { n: pending }, pending) }}
          </button>
          <span class="hint">{{ $t('gallery.made.policy') }}</span>
          <span v-if="!detector.models" class="hint">{{ $t('gallery.made.firstUse') }}</span>
        </template>
      </template>
      <span v-if="job?.state === 'failed'" class="hint err">
        <Icon name="error" :size="12" />
        {{ $t('gallery.made.failed', { error: job.error }) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.made {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
button.chip {
  cursor: pointer;
  font: inherit;
  font-size: 11px;
}
.chip em {
  font-style: normal;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--dim);
}
.chip.on em {
  color: inherit;
}
.err {
  color: var(--color-rose);
}
</style>
