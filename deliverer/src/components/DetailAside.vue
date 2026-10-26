<script setup lang="ts">
import type { PostDetail } from '@/lib/types';
import { linkedStart, megabytes, relatedSet } from '@/lib/related';

/**
 * The image detail panel over a character's grid. It walks a *related set*
 * (lib/related.ts): the post's pages, then the images of the other source's
 * post dedupe linked -- click a tile or press ← → to switch, F or the
 * preview opens the fullscreen viewer on the same image, and stepping in the
 * viewer moves the panel too.
 */
const props = defineProps<{ post: PostDetail }>();
const emit = defineEmits<{ close: [] }>();
const { t, te } = useI18n();
const viewer = useViewer();
const src = useSources();

const set = computed(() => relatedSet(props.post));
const at = ref(0);
const cur = computed(() => set.value[at.value] ?? null);

/** the row behind the current image, for what only the opened post carries (identity) */
const row = computed(() =>
  cur.value && !cur.value.linked ? props.post.media.find((m) => m.idx === cur.value!.idx) : undefined,
);

const own = computed(() => set.value.filter((it) => !it.linked));
const others = computed(() => set.value.filter((it) => it.linked));
const divider = computed(() => linkedStart(set.value));
const link = computed(() => props.post.linked[0] ?? null);
const canReveal = computed(() => src.inTauri && !!cur.value?.path);

/** Display label for a source id ('pixiv' → "pixiv", 'twitter' → "X"); unknown ids show as-is. */
function srcLabel(s: string) {
  const key = `gallery.aside.source.${s}`;
  return te(key) ? t(key) : s;
}

function go(i: number) {
  if (i < 0 || i >= set.value.length) return;
  at.value = i;
  if (viewer.open) viewer.go(i);
}

function openViewer() {
  viewer.show(set.value, at.value);
}

// the viewer and the panel show the same image
watch(
  () => viewer.index,
  (i) => {
    if (viewer.open && i < set.value.length) at.value = i;
  },
);

// another post (a tile click, or the viewer stepping out of a one-image set)
watch(
  () => props.post,
  () => {
    if (viewer.open) {
      viewer.replace(set.value);
      at.value = viewer.index;
    } else at.value = 0;
  },
);

function onKey(e: KeyboardEvent) {
  if (e.defaultPrevented || viewer.open) return;
  const tag = (e.target as HTMLElement | null)?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    if (set.value.length < 2) return;
    e.preventDefault();
    go((at.value + (e.key === 'ArrowRight' ? 1 : -1) + set.value.length) % set.value.length);
  } else if ((e.key === 'f' || e.key === 'F') && !e.metaKey && !e.ctrlKey && cur.value) {
    e.preventDefault();
    openViewer();
  }
}

onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));

/** the preview is a square for portrait art (cropped, never a strip); landscape art keeps its own ratio */
const artStyle = computed(() => {
  const w = cur.value?.width ?? 0;
  const h = cur.value?.height ?? 0;
  return { aspectRatio: w && h && w > h ? `${w} / ${h}` : '1 / 1' };
});

/** "blobs/69/9a/" -- where the file sits under the library, enough to recognise it */
const storedAt = computed(() => {
  const p = cur.value?.path;
  if (!p) return '';
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.slice(-4, -1).join('/') + '/';
});
</script>

<template>
  <aside class="aside">
    <div class="phead">
      <span class="ptitle">{{ $t('gallery.aside.title') }}</span>
      <div class="spacer" />
      <span v-if="cur && cur.pages > 1" class="kv mono">
        {{ $t('gallery.aside.counter', { n: cur.page, total: cur.pages }) }}
      </span>
      <button
        v-if="cur"
        class="btn gh sm ico"
        :title="$t('gallery.aside.fullscreen')"
        :aria-label="$t('gallery.aside.fullscreen')"
        @click="openViewer"
      >
        <Icon name="expand" :size="14" />
      </button>
      <button
        class="btn gh sm ico"
        :title="$t('gallery.aside.close')"
        :aria-label="$t('gallery.aside.close')"
        @click="emit('close')"
      >
        <Icon name="close" :size="14" />
      </button>
    </div>
    <div class="content">
      <button
        v-if="cur"
        class="art"
        :style="artStyle"
        :title="$t('gallery.aside.fullscreen')"
        @click="openViewer"
      >
        <img :src="mediaUrl(cur.sha)" alt="" />
        <span v-if="cur.pages > 1" class="badge pages mono">
          {{ $t('gallery.aside.counter', { n: cur.page, total: cur.pages }) }}
        </span>
        <span class="badge dims mono">
          <Icon name="expand" :size="11" />
          {{ cur.width }} × {{ cur.height }}
        </span>
      </button>

      <div class="jp title">{{ (cur?.title ?? post.title) || $t('gallery.aside.untitled') }}</div>
      <div class="row">
        <b class="ib">
          <Icon name="user" :size="13" />
          {{
            cur?.artist_name || cur?.artist_handle || post.artist_name || post.artist_handle || post.artist_id
          }}
        </b>
        <span
          class="chip"
          :style="(cur?.source ?? post.source) === 'pixiv' ? 'color:var(--ember)' : 'color:var(--cyan)'"
        >
          {{ srcLabel(cur?.source ?? post.source) }}
        </span>
        <div class="spacer" />
        <span class="kv mono ib">
          <Icon name="calendar" :size="12" />
          {{ (cur?.posted_at ?? post.posted_at ?? '').slice(0, 10) }}
        </span>
      </div>
      <div v-if="post.state === 'gone' && !cur?.linked" class="kv" style="color: oklch(0.72 0.1 300)">
        {{ $t('gallery.aside.gone') }}
      </div>
      <div v-if="post.tags.length && !cur?.linked" class="chips">
        <span v-for="tag in post.tags" :key="tag.tag_norm" class="chip jp">{{ tag.tag_raw }}</span>
      </div>

      <section v-if="set.length > 1" class="related">
        <div class="rhead">
          <span class="ptitle">{{ $t('gallery.aside.related.title') }}</span>
          <span class="kv mono">
            {{ $t('gallery.aside.related.samePost', { id: post.external_id, n: own.length }) }}
          </span>
          <div class="spacer" />
          <a v-if="link && others.length" href="#" class="more mono" @click.prevent="go(divider)">
            {{
              $t('gallery.aside.related.more', {
                n: others.length,
                handle: link.artist_handle || link.artist_name,
                source: srcLabel(link.source),
              })
            }}
          </a>
        </div>
        <div class="strip">
          <template v-for="(it, i) in set" :key="it.key">
            <i v-if="i === divider" class="div" aria-hidden="true" />
            <button
              class="tile"
              :class="{ cur: i === at, other: it.linked }"
              :aria-current="i === at || undefined"
              :title="it.linked ? srcLabel(it.source) : $t('gallery.aside.related.page', { n: it.page })"
              @click="go(i)"
            >
              <img :src="mediaUrl(it.sha)" alt="" />
              <span v-if="!it.linked" class="lbl mono">
                {{ $t('gallery.aside.related.page', { n: it.page }) }}
              </span>
              <span v-else class="lbl src mono">{{ srcLabel(it.source) }}</span>
            </button>
          </template>
        </div>
        <p class="kv cap">
          {{
            link && others.length
              ? $t('gallery.aside.related.caption', {
                  source: srcLabel(post.source),
                  other: srcLabel(link.source),
                  id: link.external_id,
                })
              : $t('gallery.aside.related.captionPages', { source: srcLabel(post.source) })
          }}
        </p>
      </section>

      <div class="meta">
        <div>
          <span class="kv ib">
            <Icon name="image" :size="12" />
            {{ $t('gallery.aside.dimensions') }}
          </span>
          <span class="mono">{{ cur?.width }} × {{ cur?.height }}</span>
        </div>
        <div>
          <span class="kv ib">
            <Icon name="file" :size="12" />
            {{ $t('gallery.aside.file') }}
          </span>
          <span class="mono">
            {{
              cur?.bytes
                ? $t('gallery.aside.fileInfo', { n: megabytes(cur.bytes), ext: cur.ext.toUpperCase() })
                : '-'
            }}
          </span>
        </div>
        <div v-if="post.source === 'pixiv' && !cur?.linked">
          <span class="kv ib">
            <Icon name="bookmark" :size="12" />
            {{ $t('gallery.aside.bookmarks') }}
          </span>
          <span class="mono">{{ post.bookmark_count }}</span>
        </div>
        <div v-if="row">
          <span class="kv ib">
            <Icon name="users" :size="12" />
            {{ $t('gallery.aside.characters') }}
          </span>
          <span v-if="row.identity?.state === 'identified'" class="who">
            <span v-for="c in row.identity.characters" :key="c.name" :title="c.tag">
              {{ c.label }}
              <em class="mono">{{ $t('gallery.aside.score', { n: Math.round(c.score * 100) }) }}</em>
            </span>
          </span>
          <span v-else-if="row.identity" class="kv">{{ $t('gallery.aside.unidentified') }}</span>
          <span v-else class="kv">{{ $t('gallery.aside.notIdentified') }}</span>
        </div>
        <div>
          <span class="kv ib">
            <Icon name="hash" :size="12" />
            {{ $t('gallery.aside.hash') }}
          </span>
          <span class="mono">{{ cur?.sha.slice(0, 12) }}…</span>
        </div>
        <div>
          <span class="kv ib">
            <Icon name="folder" :size="12" />
            {{ $t('gallery.aside.stored') }}
          </span>
          <span class="mono" :class="{ dimmed: !cur?.stored }">
            {{ cur?.stored ? storedAt || cur.variant : $t('gallery.aside.notStored') }}
          </span>
        </div>
      </div>

      <div v-if="link" class="linked">
        <div class="ltitle">
          <span class="ib">
            <Icon name="link" :size="13" />
            {{ $t('gallery.aside.sameImageOn', { source: srcLabel(link.source) }) }}
          </span>
          <span class="mono">{{ link.reason }}</span>
        </div>
        <div class="lrow">
          <button
            v-if="others.length"
            class="lthumb"
            :title="$t('gallery.aside.fullscreen')"
            @click="go(divider)"
          >
            <img :src="mediaUrl(others[0]!.sha)" alt="" />
          </button>
          <div class="lmeta">
            <a href="#" class="mono" @click.prevent="openExternal(link.permalink)">
              {{ link.artist_handle ? '@' + link.artist_handle : link.permalink }}
            </a>
            <span class="kv mono">
              {{ (link.posted_at ?? '').slice(0, 10) }}
              <template v-if="others.length">· {{ others[0]!.width }} × {{ others[0]!.height }}</template>
            </span>
          </div>
        </div>
        <p class="kv note">
          {{
            $t('gallery.aside.keptNote', {
              kept: srcLabel(set.find((it) => it.stored)?.source ?? post.source),
              other: srcLabel(link.source),
            })
          }}
        </p>
      </div>

      <div class="row actions">
        <button class="btn pri" @click="openExternal(cur?.permalink ?? post.permalink)">
          <Icon name="external" :size="13" />
          {{ $t('gallery.aside.openOn', { source: srcLabel(cur?.source ?? post.source) }) }}
        </button>
        <button
          class="btn gh"
          :disabled="!canReveal"
          :title="
            canReveal
              ? $t('gallery.aside.revealHint')
              : cur?.path
                ? $t('gallery.aside.revealDesktop')
                : $t('gallery.aside.revealNone')
          "
          @click="cur?.path && revealInFolder(cur.path)"
        >
          <Icon name="folder" :size="13" />
          {{ $t('gallery.aside.reveal') }}
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* laid over the grid (and its backdrop), never beside it: the grid does not reflow */
.aside {
  position: absolute;
  z-index: 5;
  top: 0;
  right: 0;
  bottom: 0;
  width: 396px;
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
.ico {
  width: 25px;
  padding: 0;
  justify-content: center;
}
.content {
  flex: 1;
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: none;
}
/* the preview never shrinks: the body scrolls instead */
.art {
  position: relative;
  flex: none;
  width: 100%;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line-soft);
  background: var(--bg);
  cursor: zoom-in;
}
.art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.badge {
  position: absolute;
  bottom: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  background: oklch(0.15 0.024 265 / 0.78);
  backdrop-filter: blur(6px);
}
.badge.dims {
  right: 8px;
  color: var(--cyan);
  border: 1px solid color-mix(in oklch, var(--cyan) 60%, transparent);
}
.badge.pages {
  left: 8px;
  color: var(--mut);
  border: 1px solid var(--line);
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
.related {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rhead {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.rhead .ptitle {
  font-size: 10px;
  flex: none;
}
.more {
  flex: none;
  font-size: 11px;
  color: var(--cyan);
  text-decoration: none;
}
.strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
}
.tile {
  position: relative;
  flex: none;
  width: 64px;
  height: 64px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line-soft);
  background: var(--bg);
}
.tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.tile.other img {
  opacity: 0.85;
}
.tile.cur {
  box-shadow:
    inset 0 0 0 2px var(--ember),
    0 0 10px color-mix(in oklch, var(--ember) 50%, transparent);
}
.lbl {
  position: absolute;
  top: 3px;
  left: 3px;
  padding: 1px 4px;
  font-size: 9px;
  font-weight: 600;
  color: var(--tx);
  background: oklch(0.1 0.01 60 / 0.8);
}
.lbl.src {
  left: auto;
  right: 3px;
  color: var(--cyan);
}
.div {
  flex: none;
  width: 1px;
  margin: 6px 0;
  background: var(--line-soft);
}
.cap {
  font-size: 10.5px;
  margin: 0;
}
/* the facts and the actions sit at the foot of the panel; a short post leaves the gap above them */
.meta {
  margin-top: auto;
  border-top: 1px solid var(--line-soft);
  border-bottom: 1px solid var(--line-soft);
  padding: 6px 0;
}
.meta div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
  font-size: 11.5px;
}
.meta .mono {
  text-align: right;
}
.dimmed {
  color: var(--dim);
}
.who {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px 10px;
  text-align: right;
}
.who em {
  font-style: normal;
  color: var(--dim);
  margin-left: 3px;
}
.linked {
  border: 1px solid color-mix(in oklch, var(--cyan) 45%, transparent);
  border-radius: 0;
  background: color-mix(in oklch, var(--cyan) 8%, transparent);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
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
.lrow {
  display: flex;
  align-items: center;
  gap: 10px;
}
.lthumb {
  flex: none;
  width: 44px;
  height: 44px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line-soft);
  cursor: zoom-in;
}
.lthumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.lmeta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  font-size: 11.5px;
}
.lmeta a {
  color: var(--cyan);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note {
  margin: 0;
  font-size: 10.5px;
}
.actions {
  gap: 7px;
}
.actions .btn {
  flex: 1;
  justify-content: center;
}
</style>
