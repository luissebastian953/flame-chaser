<script setup lang="ts">
/**
 * Who is in this character's images (coreflame/identify.py): chips for
 * identified / unidentified / not identified yet, and one chip per character
 * named, to narrow the grid. Names only label -- nothing is removed. Offers
 * the `label` job for images stored before naming existed.
 */
import type { IdentState } from '@/lib/types';

const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const jobs = useJobs();

const INSTALL = "pip install 'reaver[classify]'"; // data, shown verbatim
const SHOWN = 8; // character chips before "+N more"

const jobId = ref<string | null>(null);
const job = computed(() => (jobId.value ? (jobs.jobs.find((j) => j.id === jobId.value) ?? null) : null));
const running = computed(() => !!job.value && ['queued', 'running'].includes(job.value.state));
const all = ref(false);

const counts = computed(() => lib.characters?.counts ?? { identified: 0, unidentified: 0, pending: 0 });
const pending = computed(() => counts.value.pending);
const ident = computed(() => lib.characters?.identifier ?? null);
// "Not identified yet" only exists while something is
const states = computed(() => IDENT_STATES.filter((s) => s !== 'pending' || pending.value > 0));
const named = computed(() => lib.characters?.characters ?? []);
const visible = computed(() => (all.value ? named.value : named.value.slice(0, SHOWN)));

function toggle(s: IdentState) {
  const on = lib.who.includes(s);
  const next = on ? lib.who.filter((x) => x !== s) : [...lib.who, s];
  if (!next.some((x) => states.value.includes(x))) return; // never an empty grid by accident
  lib.character = null; // a state choice replaces a character choice

  void lib.setWho(props.slug, next);
}

function pick(name: string) {
  void lib.setCharacter(props.slug, lib.character === name ? null : name);
}

async function identifyNow() {
  jobId.value = await jobs.submit('label');
}

// the jobs store follows the daemon's events; when our job ends, recount and redraw
watch(
  () => job.value?.state,
  async (state) => {
    if (state && !['queued', 'running'].includes(state)) {
      await Promise.all([lib.loadCharacters(props.slug), lib.loadGrid(props.slug, true)]);
    }
  },
);
</script>

<template>
  <div class="who">
    <div class="row">
      <span class="ptitle">{{ $t('gallery.who.title') }}</span>
      <button
        v-for="s in states"
        :key="s"
        class="chip"
        :class="{ on: !lib.character && lib.who.includes(s) }"
        :aria-pressed="!lib.character && lib.who.includes(s)"
        @click="toggle(s)"
      >
        {{ $t(`gallery.who.state.${s}`) }}
        <em>{{ counts[s] }}</em>
      </button>
      <template v-if="pending > 0 && ident">
        <span v-if="!ident.enabled" class="hint">{{ $t('gallery.who.off') }}</span>
        <span v-else-if="!ident.available" class="hint">
          <Icon name="warning" :size="12" />
          {{ $t('gallery.who.unavailable', { cmd: INSTALL }) }}
        </span>
        <span v-else-if="running" class="hint data">
          <Icon name="loader" class="spin" :size="12" />
          {{
            job?.total
              ? $t('gallery.who.identifying', { done: job.done, total: job.total })
              : $t('gallery.who.identifyingStarting')
          }}
        </span>
        <template v-else>
          <button class="btn sm" @click="identifyNow">
            <Icon name="scan" :size="13" />
            {{ $t('gallery.who.identifyNow', { n: pending }, pending) }}
          </button>
          <span class="hint">{{ $t('gallery.who.policy') }}</span>
          <span v-if="!ident.models" class="hint">{{ $t('gallery.who.firstUse') }}</span>
        </template>
      </template>
      <span v-if="job?.state === 'failed'" class="hint err">
        <Icon name="error" :size="12" />
        {{ $t('gallery.who.failed', { error: job.error }) }}
      </span>
    </div>
    <div v-if="named.length" class="row">
      <span class="ptitle">{{ $t('gallery.who.characters') }}</span>
      <button
        v-for="c in visible"
        :key="c.name"
        class="chip"
        :class="{ on: lib.character === c.name }"
        :aria-pressed="lib.character === c.name"
        :title="c.name"
        @click="pick(c.name)"
      >
        <Icon name="user" :size="11" />
        {{ c.label }}
        <em>{{ c.count }}</em>
      </button>
      <button v-if="named.length > SHOWN" class="more" @click="all = !all">
        {{ all ? $t('gallery.who.fewer') : $t('gallery.who.more', { n: named.length - SHOWN }) }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.who {
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
.more {
  background: none;
  border: none;
  padding: 2px 4px;
  font-size: 11px;
  color: var(--mut);
  cursor: pointer;
}
.err {
  color: var(--color-rose);
}
</style>
