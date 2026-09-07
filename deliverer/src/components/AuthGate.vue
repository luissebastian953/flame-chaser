<script setup lang="ts">
/**
 * First-launch gate: shown once the daemon is up and no source is connected.
 * "Browse offline" dismisses it for this install (localStorage) -- the
 * gallery works without a session, only crawling needs one. Reappears from
 * Settings › Accounts, never on its own again.
 */

const src = useSources();
</script>

<template>
  <div class="scrim">
    <div class="gate panel poly">
      <div class="phead head">
        <div>
          <div class="title">{{ $t('auth.gate.title') }}</div>
          <div class="data text-small text-dim mt-5">{{ $t('auth.gate.lead') }}</div>
        </div>
      </div>
      <div class="list">
        <SourceCard source="twitter" />
        <SourceCard source="pixiv" />
        <SourceCard source="other" />
      </div>
      <div class="foot">
        <span class="data text-small text-dim">{{ $t('auth.gate.foot') }}</span>
        <div class="spacer" />
        <button class="btn" @click="src.dismiss()">{{ $t('auth.gate.offline') }}</button>
        <button v-if="src.anyConnected" class="btn pri" @click="src.dismiss()">
          {{ $t('auth.gate.continue') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrim {
  position: absolute;
  inset: 0;
  background: oklch(0 0 0 / 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
.gate {
  width: min(700px, 92%);
  --cut: 14px;
}
.head {
  padding: 22px 28px 18px;
}
.title {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.list {
  padding: 22px 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 28px;
  border-top: 1px solid var(--line-soft);
  background: var(--bg);
}
</style>
