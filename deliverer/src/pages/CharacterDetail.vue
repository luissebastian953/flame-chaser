<script setup lang="ts">
const props = defineProps<{ slug: string }>();
const lib = useLibrary();
const sentinel = ref<HTMLElement | null>(null);
let io: IntersectionObserver | null = null;

const w = computed(() => lib.watches.find((x) => x.slug === props.slug));
const suggested = computed(() => lib.tags.filter((t) => t.state === 'suggested').slice(0, 8));
const watched = computed(() => lib.tags.filter((t) => t.state === 'watched'));

async function load() {
  await Promise.all([lib.loadGrid(props.slug, true), lib.loadTags(props.slug)]);
}

onMounted(async () => {
  await load();

  // keyset "load more" when the sentinel scrolls into view
  io = new IntersectionObserver((es) => {
    if (es[0]?.isIntersecting) lib.loadGrid(props.slug);
  });

  if (sentinel.value) io.observe(sentinel.value);
});

onUnmounted(() => {
  io?.disconnect();
  lib.closeDetail();
});

watch(() => props.slug, load);
</script>

<template>
  <div class="top">
    <RouterLink
      to="/gallery"
      class="btn gh sm"
      :title="$t('gallery.detail.back')"
      :aria-label="$t('gallery.detail.back')"
    >
      ‹
    </RouterLink>
    <div>
      <div class="h1">
        {{ w?.label || slug }}
        <span class="jp sub">{{ w?.pixiv_tags[0] }}</span>
      </div>
      <div class="sub">
        {{
          lib.grid.done
            ? $t('gallery.detail.images', lib.grid.items.length)
            : $t('gallery.detail.imagesMore', { n: lib.grid.items.length })
        }}
      </div>
    </div>
  </div>
  <div class="body" :class="{ withAside: lib.detail }">
    <div v-if="lib.tags.length" class="tags">
      <span class="ptitle">{{ $t('gallery.detail.observedTags') }}</span>
      <span
        v-for="t in watched"
        :key="t.tag_norm"
        class="chip jp on"
        :title="$t('gallery.detail.state.watched')"
      >
        {{ t.tag_raw }}
        <em>{{ $t('gallery.detail.share', { n: Math.round(t.share * 100) }) }}</em>
      </span>
      <span
        v-for="t in suggested"
        :key="t.tag_norm"
        class="chip jp"
        :title="$t('gallery.detail.state.suggested')"
      >
        {{ t.tag_raw }}
        <em>{{ $t('gallery.detail.share', { n: Math.round(t.share * 100) }) }}</em>
        <button class="act" @click="lib.tagAction(slug, t.tag_raw, 'watch')">
          {{ $t('gallery.detail.watch') }}
        </button>
        <button class="act dim" @click="lib.tagAction(slug, t.tag_raw, 'ignore')">
          {{ $t('gallery.detail.ignore') }}
        </button>
      </span>
    </div>
    <div class="masonry">
      <img
        v-for="it in lib.grid.items"
        :key="it.sha256 + it.idx"
        :src="mediaUrl(it.sha256)"
        loading="lazy"
        decoding="async"
        :style="{ aspectRatio: it.width && it.height ? `${it.width}/${it.height}` : '3/4' }"
        alt=""
        @click="lib.openDetail(it.source, it.external_id)"
      />
    </div>
    <div ref="sentinel" class="kv" style="padding: 16px; text-align: center">
      {{ lib.grid.done ? $t('gallery.detail.end') : $t('gallery.detail.loading') }}
    </div>
  </div>
  <DetailAside v-if="lib.detail" :post="lib.detail" @close="lib.closeDetail()" />
</template>

<style scoped>
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 12px;
}
.chip em {
  font-style: normal;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--dim);
}
.chip.on {
  border-color: oklch(0.4 0.06 58);
  color: var(--ember);
}
.act {
  background: none;
  border: none;
  font-size: 10px;
  color: var(--moss);
  font-weight: 600;
  padding: 0 2px;
}
.act.dim {
  color: var(--dim);
  font-weight: 400;
}
.masonry {
  column-count: 5;
  column-gap: 8px;
}
.withAside .masonry {
  column-count: 3;
}
.masonry img {
  width: 100%;
  display: block;
  border-radius: 0;
  margin-bottom: 8px;
  break-inside: avoid;
  background: var(--surf2);
  cursor: pointer;
}
@media (max-width: 1100px) {
  .masonry {
    column-count: 4;
  }
}
</style>
