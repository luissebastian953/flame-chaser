<script setup lang="ts">
/**
 * One source row: icon, name, what it gives, state, and the Connect action.
 * Desktop: Connect opens the shell's login window. Browser mode: Connect
 * unfolds a paste form. Used by the first-launch gate and Settings › Accounts.
 */

const props = defineProps<{ source: Source | 'other' }>();
const src = useSources();
const { t } = useI18n();
const paste = ref(false); // browser mode: "Sign in" explains; the form is one click further
const f = ref({ PHPSESSID: '', auth_token: '', ct0: '' });
const showForm = ref(false);
const localErr = ref('');

const GLYPH = { pixiv: 'px', twitter: '𝕏', other: '◎' } as const;

const meta = computed(() => ({
  name: t(`auth.source.${props.source}.name`),
  blurb: t(`auth.source.${props.source}.blurb`),
  glyph: GLYPH[props.source],
}));

const state = computed(() => {
  if (props.source === 'other') return 'soon' as const;
  const s = src.status;
  if (!s) return 'unknown' as const;
  if (props.source === 'pixiv') {
    if (!s.pixiv.authed) return 'off' as const;
    if (s.pixiv.verified === false) return 'expired' as const;
    if (s.pixiv.verified === null) return 'pending' as const;
    return 'on' as const;
  }
  return s.twitter.authed ? ('on' as const) : ('off' as const);
});

const who = computed(() => {
  const s = src.status;
  if (props.source === 'pixiv' && s?.pixiv.user_id) return t('auth.source.user', { id: s.pixiv.user_id });
  if (props.source === 'twitter' && s?.twitter.authed)
    return s.twitter.from_browser
      ? t('auth.source.via', { browser: s.twitter.from_browser })
      : t('auth.source.signedIn');
  return '';
});

const busy = computed(() => src.busy === props.source);

async function connect() {
  if (props.source === 'other') return;
  localErr.value = '';
  if (src.inTauri) await src.connectViaWindow(props.source);
  else {
    paste.value = !paste.value;
    showForm.value = false;
  }
}

async function submitPaste() {
  if (props.source === 'other') return;
  localErr.value = '';
  try {
    await src.submit(
      props.source,
      props.source === 'pixiv'
        ? { PHPSESSID: f.value.PHPSESSID }
        : { auth_token: f.value.auth_token, ct0: f.value.ct0 },
    );

    paste.value = false;
    f.value = { PHPSESSID: '', auth_token: '', ct0: '' };
  } catch (e) {
    localErr.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <div class="card" :class="{ soon: state === 'soon', on: state === 'on' }">
    <div class="row">
      <div class="glyph" :class="{ cyan: source === 'twitter', ember: source === 'pixiv' }">
        {{ meta.glyph }}
      </div>
      <div class="flex-1 min-w-0">
        <div class="name">
          {{ meta.name }}
          <span v-if="state === 'on'" class="chip on ml-10">
            {{ $t('auth.source.connected') }}
            <span v-if="who" class="data">· {{ who }}</span>
          </span>
          <span v-else-if="state === 'expired'" class="chip err ml-10">
            {{ $t('auth.source.sessionExpired') }}
          </span>
          <span v-else-if="state === 'pending'" class="chip off ml-10">
            {{ $t('auth.source.storedChecking') }}
          </span>
        </div>
        <div class="data text-small text-dim">{{ meta.blurb }}</div>
      </div>
      <template v-if="state === 'soon'">
        <span class="chip off">{{ $t('auth.source.comingSoon') }}</span>
      </template>
      <template v-else-if="state === 'on' || state === 'pending'">
        <button v-if="source === 'pixiv'" class="btn gh sm" :disabled="busy" @click="src.verifyPixiv()">
          {{ $t('auth.source.check') }}
        </button>
        <button class="btn gh sm" :disabled="busy" @click="src.disconnect(source as Source)">
          {{ $t('auth.source.signOut') }}
        </button>
      </template>
      <template v-else>
        <button class="btn pri" :disabled="busy" @click="connect">
          {{
            busy
              ? $t('auth.source.busy')
              : state === 'expired'
                ? $t('auth.source.signInAgain')
                : $t('auth.source.signIn')
          }}
        </button>
      </template>
    </div>

    <!-- Browser-mode ONLY (no second window to sign in with). The desktop app
         never shows this: Sign in opens the site's own login page. -->
    <div v-if="paste && source !== 'other'" class="paste">
      <div class="devnote">
        <span class="chip off">{{ $t('auth.source.browserMode') }}</span>
        <span>
          <i18n-t keypath="auth.source.browserModeLead" tag="span">
            <template #signIn>
              <b>{{ $t('auth.source.signIn') }}</b>
            </template>
            <template #site>{{ meta.name }}</template>
          </i18n-t>
          <button class="link" @click="showForm = !showForm">
            {{ showForm ? $t('auth.source.pasteToggleHide') : $t('auth.source.pasteToggleShow') }}
          </button>
        </span>
      </div>
      <template v-if="!showForm" />
      <template v-else-if="source === 'pixiv'">
        <div class="field">
          <label>PHPSESSID</label>
          <input
            v-model="f.PHPSESSID"
            class="data text-small"
            placeholder="12345678_abcdefghijklmnopqrstuvwxyz"
            autocomplete="off"
            spellcheck="false"
            @keydown.enter="submitPaste"
          />
          <div class="hint">{{ $t('auth.source.pixivHint') }}</div>
        </div>
      </template>
      <template v-else>
        <div class="grid2">
          <div class="field">
            <label>auth_token</label>
            <input v-model="f.auth_token" class="data text-small" autocomplete="off" spellcheck="false" />
          </div>
          <div class="field">
            <label>ct0</label>
            <input
              v-model="f.ct0"
              class="data text-small"
              autocomplete="off"
              spellcheck="false"
              @keydown.enter="submitPaste"
            />
          </div>
        </div>
        <div class="hint">{{ $t('auth.source.xHint') }}</div>
      </template>
      <div v-if="showForm" class="flex gap-10 items-center">
        <button class="btn pri sm" :disabled="busy" @click="submitPaste">
          {{ busy ? $t('auth.source.verifying') : $t('auth.source.save') }}
        </button>
        <button class="btn gh sm" @click="paste = false">{{ $t('auth.source.cancel') }}</button>
        <span v-if="localErr" class="err text-small">{{ localErr }}</span>
      </div>
    </div>
    <div v-else-if="src.error && busy === false && state === 'expired'" class="err text-small mt-5">
      {{ src.status?.pixiv.error }}
    </div>
  </div>
</template>

<style scoped>
.card {
  border: 1px solid var(--line-soft);
  background: var(--surf2);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.card.on {
  border-color: color-mix(in oklch, var(--ember) 35%, var(--line-soft));
}
.card.soon {
  opacity: 0.55;
}
.row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.glyph {
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-soft);
  background: var(--bg);
  font: 600 15px var(--mono);
  color: var(--dim);
}
.glyph.cyan {
  color: var(--cyan);
}
.glyph.ember {
  color: var(--ember);
}
.name {
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
}
.paste {
  border-top: 1px solid var(--line-soft);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.devnote {
  font-size: 12.5px;
  color: var(--mut);
  display: flex;
  gap: 10px;
  align-items: flex-start;
  line-height: 1.5;
}
.devnote b {
  color: var(--tx);
}
.link {
  background: none;
  border: 0;
  padding: 0;
  color: var(--cyan);
  font: inherit;
  cursor: pointer;
  margin-left: 6px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
</style>
