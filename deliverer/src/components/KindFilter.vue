<script setup lang="ts">
/**
 * The archive keeps illustrations and anime screencaps (coreflame/kinds.py
 * KEEP) for characters with the image-kind filter on (the default); the daemon
 * throws everything else away as it downloads. This row narrows the grid
 * between what the character holds -- every kind when its filter is off -- and
 * offers the `label` job: label what is unlabeled, then remove what is not kept.
 */
import type { KindFilter } from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const jobs = useJobs();
const del = useDeletion();
const { t } = useI18n();
// By tag (stores/deletion.ts): a chip marks the images of that kind instead of filtering
const selecting = computed(() => del.mode === 'tag');

// data, not prose: shown verbatim inside the translated sentence
const INSTALL = "pip install 'reaver[classify]'";

const jobId = ref<string | null>(null);
const job = computed(() => (jobId.value ? (jobs.jobs.find((j) => j.id === jobId.value) ?? null) : null));
const labeling = computed(() => !!job.value && ['queued', 'running'].includes(job.value.state));
const unlabeled = computed(() => lib.kinds?.counts.unlabeled ?? 0);
// stored before the character's gender filter was set: the label job checks them
const peoplePending = computed(() => lib.kinds?.people?.pending ?? 0);

// stored before the keep rule, labeled as a kind that is now thrown away
const filterOn = computed(() => lib.watches.find((w) => w.slug === props.slug)?.kind_filter !== false);

const discardable = computed(() => {
  const c = lib.kinds?.counts;

  return c && filterOn.value ? c.photo + c.render + c.other : 0;
});

// "Not labeled yet" only exists while something is unlabeled
// what this character's grid can hold (every kind with its filter off)
const can = computed(() => lib.kindsFor(props.slug));
const chips = computed(() => can.value.filter((k) => k !== 'unlabeled' || unlabeled.value > 0));

function toggle(k: KindFilter) {
  if (selecting.value) {
    const total = Object.values(lib.kinds?.counts ?? {}).reduce((a, b) => a + b, 0);
    void del.toggleTerm('kind', k, t(`gallery.kinds.name.${k}`), lib.gridQuery(props.slug), total);
    return;
  }
  const on = lib.show.includes(k);
  const next = on ? lib.show.filter((x) => x !== k) : [...lib.show, k];
  if (!next.some((x) => can.value.includes(x))) return; // never an empty grid by accident

  void lib.setShow(props.slug, next);
}

async function runLabelJob() {
  jobId.value = await jobs.submit('label');
}

// the jobs store follows the daemon's events; when our job ends, recount and redraw
watch(
  () => job.value?.state,
  async (state) => {
    if (state && !['queued', 'running'].includes(state)) {
      await Promise.all([lib.loadKinds(props.slug), lib.loadGrid(props.slug, true)]);
    }
  },
);
</script>

<template>
  <div class="kinds">
    <span class="ptitle">{{ $t('gallery.kinds.show') }}</span>
    <button
      v-for="k in chips"
      :key="k"
      class="chip"
      :class="selecting ? { pick: true, sel: del.isTerm('kind', k) } : { on: lib.show.includes(k) }"
      :aria-pressed="selecting ? del.isTerm('kind', k) : lib.show.includes(k)"
      @click="toggle(k)"
    >
      <Icon v-if="selecting && del.isTerm('kind', k)" name="close" :size="10" />
      {{ $t(`gallery.kinds.name.${k}`) }}
      <em>{{ lib.kinds?.counts[k] ?? 0 }}</em>
    </button>
    <template v-if="unlabeled > 0 || discardable > 0 || peoplePending > 0">
      <span v-if="lib.kinds && !lib.kinds.labeler.available" class="hint">
        <Icon name="warning" :size="12" />
        {{ $t('gallery.kinds.unavailable', { cmd: INSTALL }) }}
      </span>
      <span v-else-if="labeling" class="hint data">
        <Icon name="loader" class="spin" :size="12" />
        {{
          job?.total
            ? $t('gallery.kinds.labeling', { done: job.done, total: job.total })
            : $t('gallery.kinds.labelingStarting')
        }}
      </span>
      <template v-else>
        <button class="btn sm" @click="runLabelJob">
          <Icon v-if="unlabeled > 0" name="scan" :size="13" />
          <Icon v-else-if="discardable > 0" name="trash" :size="13" />
          <Icon v-else name="users" :size="13" />
          {{
            unlabeled > 0
              ? $t('gallery.kinds.labelNow', { n: unlabeled }, unlabeled)
              : discardable > 0
                ? $t('gallery.kinds.removeNow', { n: discardable }, discardable)
                : $t('gallery.kinds.checkPeople', { n: peoplePending }, peoplePending)
          }}
        </button>
        <span class="hint">{{ $t('gallery.kinds.policy') }}</span>
        <span v-if="unlabeled > 0 && lib.kinds && !lib.kinds.labeler.models" class="hint">
          {{ $t('gallery.kinds.firstUse') }}
        </span>
      </template>
    </template>
    <span v-if="job?.state === 'failed'" class="hint err">
      <Icon name="error" :size="12" />
      {{ $t('gallery.kinds.failed', { error: job.error }) }}
    </span>
  </div>
</template>

<style scoped>
.kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 12px;
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
