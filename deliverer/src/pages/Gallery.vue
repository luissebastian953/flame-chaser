<script setup lang="ts">
const lib = useLibrary();
const { t } = useI18n();
onMounted(() => lib.loadWatches());

const totalPosts = computed(() => lib.watches.reduce((n, w) => n + (w.post_count ?? 0), 0));

const sub = computed(() =>
  t('gallery.gallery.sub', {
    posts: t('gallery.gallery.postCount', totalPosts.value),
    characters: t('gallery.gallery.characterCount', lib.watches.length),
  }),
);
</script>

<template>
  <div class="top">
    <div>
      <div class="h1">{{ $t('gallery.gallery.title') }}</div>
      <div class="sub">{{ sub }}</div>
    </div>
  </div>
  <div class="body">
    <div v-if="lib.watches.length" class="cards">
      <RouterLink v-for="w in lib.watches" :key="w.slug" :to="`/gallery/${w.slug}`" class="card">
        <div class="cover">
          <img v-if="w.cover_sha" :src="mediaUrl(w.cover_sha)" loading="lazy" alt="" />
          <div v-else class="empty">{{ $t('gallery.gallery.noImages') }}</div>
        </div>
        <div class="meta">
          <b>{{ w.label || w.slug }}</b>
          <span class="jp kv">{{ w.pixiv_tags[0] }}</span>
        </div>
        <div class="kv stats">
          <span>
            <Icon name="images" :size="13" />
            <span class="num">{{ w.post_count ?? 0 }}</span>
            {{ $t('gallery.gallery.posts', w.post_count ?? 0) }}
          </span>
          <span v-if="w.latest_posted_at">
            <Icon name="calendar" :size="13" />
            {{ $t('gallery.gallery.latest', { date: w.latest_posted_at.slice(0, 10) }) }}
          </span>
        </div>
      </RouterLink>
    </div>
    <div v-else class="empty">{{ $t('gallery.gallery.empty') }}</div>
  </div>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 20px 18px;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: inherit;
}
.cover {
  aspect-ratio: 4 / 3;
  border-radius: 0;
  border: 1px solid var(--line-soft);
  background: var(--surf2);
  overflow: hidden;
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.meta {
  display: flex;
  align-items: baseline;
  gap: 7px;
}
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.stats > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
</style>
