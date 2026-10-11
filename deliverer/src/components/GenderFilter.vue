<script setup lang="ts">
/**
 * Who may be in a character's pictures (coreflame/people.py): Both, or Female /
 * Male with Full (only that gender) or Partial (the other one as a minority).
 * Used by the character form and by Settings › Characters for the default.
 */
import type { Gender, GenderMode } from '@/lib/types';

const gender = defineModel<Gender>('gender', { required: true });
const mode = defineModel<GenderMode>('mode', { required: true });

const GENDERS: Gender[] = ['any', 'female', 'male'];
const MODES: GenderMode[] = ['full', 'partial'];

const hintKey = computed(() =>
  gender.value === 'any' ? 'any' : `${gender.value}${mode.value === 'full' ? 'Full' : 'Partial'}`,
);
</script>

<template>
  <div class="gender">
    <div class="flex items-center gap-10 flex-wrap">
      <div class="seg" role="group" :aria-label="$t('character.gender.label')">
        <button
          v-for="g in GENDERS"
          :key="g"
          type="button"
          class="chip"
          :class="{ on: gender === g }"
          :aria-pressed="gender === g"
          @click="gender = g"
        >
          {{ $t(`character.gender.${g}`) }}
        </button>
      </div>
      <div v-if="gender !== 'any'" class="seg" role="group">
        <button
          v-for="m in MODES"
          :key="m"
          type="button"
          class="chip"
          :class="{ on: mode === m }"
          :aria-pressed="mode === m"
          @click="mode = m"
        >
          {{ $t(`character.gender.${m}`) }}
        </button>
      </div>
    </div>
    <div class="hint">{{ $t(`character.gender.hint.${hintKey}`) }}</div>
    <div v-if="gender !== 'any'" class="hint">{{ $t('character.gender.cost') }}</div>
  </div>
</template>

<style scoped>
.gender {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.seg {
  display: flex;
  gap: 4px;
}
.seg .chip {
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
</style>
