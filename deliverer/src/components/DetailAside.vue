<script setup lang="ts">
import type { PostDetail } from '@/lib/types';

const props = defineProps<{ post: PostDetail }>();
const emit = defineEmits<{ close: [] }>();
const { t, te } = useI18n();
const first = computed(() => props.post.media.find((m) => m.state === 'stored' && m.sha256) ?? null);

/** Display label for a source id ('pixiv' → "pixiv", 'twitter' → "X"); unknown ids show as-is. */
function srcLabel(s: string) {
  const key = `gallery.aside.source.${s}`;
  return te(key) ? t(key) : s;
}

async function open(url: string) {
  try {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
  } catch {
    window.open(url, '_blank');
  }
}
</script>

<template>
  <aside class="aside">
    <div class="phead">
      <span class="ptitle">{{ $t('gallery.aside.title') }}</span>
      <div class="spacer" />
      <span class="kv mono">{{ $t('gallery.aside.pages', post.media.length) }}</span>
      <button
        class="btn gh sm"
        :title="$t('gallery.aside.close')"
        :aria-label="$t('gallery.aside.close')"
        @click="emit('close')"
      >
        <Icon name="close" :size="14" />
      </button>
    </div>
    <div class="content">
      <img v-if="first?.sha256" :src="mediaUrl(first.sha256)" alt="" />
      <div class="jp title">{{ post.title || $t('gallery.aside.untitled') }}</div>
      <div class="row">
        <b class="ib">
          <Icon name="user" :size="13" />
          {{ post.artist_name || post.artist_handle || post.artist_id }}
        </b>
        <span class="chip" :style="post.source === 'pixiv' ? 'color:var(--ember)' : 'color:var(--cyan)'">
          {{ srcLabel(post.source) }}
        </span>
        <div class="spacer" />
        <span class="kv mono ib">
          <Icon name="calendar" :size="12" />
          {{ (post.posted_at ?? '').slice(0, 10) }}
        </span>
      </div>
      <div v-if="post.state === 'gone'" class="kv" style="color: oklch(0.72 0.1 300)">
        {{ $t('gallery.aside.gone') }}
      </div>
      <div class="chips">
        <span v-for="tag in post.tags" :key="tag.tag_norm" class="chip jp">{{ tag.tag_raw }}</span>
      </div>
      <div class="meta">
        <div>
          <span class="kv ib">
            <Icon name="image" :size="12" />
            {{ $t('gallery.aside.dimensions') }}
          </span>
          <span class="mono">{{ first?.width }} × {{ first?.height }}</span>
        </div>
        <div>
          <span class="kv ib">
            <Icon name="file" :size="12" />
            {{ $t('gallery.aside.file') }}
          </span>
          <span class="mono">
            {{ first?.bytes ? $t('gallery.aside.fileSize', { n: (first.bytes / 1048576).toFixed(2) }) : '—' }}
          </span>
        </div>
        <div v-if="post.source === 'pixiv'">
          <span class="kv ib">
            <Icon name="bookmark" :size="12" />
            {{ $t('gallery.aside.bookmarks') }}
          </span>
          <span class="mono">{{ post.bookmark_count }}</span>
        </div>
        <div>
          <span class="kv ib">
            <Icon name="hash" :size="12" />
            {{ $t('gallery.aside.hash') }}
          </span>
          <span class="mono">{{ first?.sha256?.slice(0, 12) }}…</span>
        </div>
      </div>
      <div v-if="post.linked.length" class="linked">
        <div class="ltitle">
          <span class="ib">
            <Icon name="link" :size="13" />
            {{ $t('gallery.aside.sameImageOn', { source: srcLabel(post.linked[0]?.source ?? '') }) }}
          </span>
          <span class="mono">{{ post.linked[0]?.reason }}</span>
        </div>
        <a href="#" @click.prevent="open(post.linked[0]!.permalink)">{{ post.linked[0]?.permalink }}</a>
      </div>
      <div class="row">
        <button class="btn" @click="open(post.permalink)">
          <Icon name="external" :size="13" />
          {{ $t('gallery.aside.openOn', { source: srcLabel(post.source) }) }}
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.aside {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 388px;
  background: var(--surf);
  border-left: 1px solid var(--line);
  box-shadow: -24px 0 48px oklch(0.1 0.01 60 / 0.5);
  display: flex;
  flex-direction: column;
  animation: in 0.2s ease-out;
}
@keyframes in {
  from {
    transform: translateX(100%);
  }
  to {
    transform: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .aside {
    animation: none;
  }
}
.content {
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
}
.content > img {
  width: 100%;
  border-radius: 0;
  border: 1px solid var(--line-soft);
}
.title {
  font-size: 14px;
  font-weight: 600;
}
.row {
  display: flex;
  align-items: center;
  gap: 9px;
}
.ib {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.meta {
  border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
  padding: 6px 0;
}
.meta div {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 11.5px;
}
.linked {
  border: 1px solid color-mix(in oklch, var(--cyan) 45%, transparent);
  border-radius: 0;
  background: color-mix(in oklch, var(--cyan) 8%, transparent);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ltitle {
  color: var(--cyan);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  display: flex;
  justify-content: space-between;
}
</style>
