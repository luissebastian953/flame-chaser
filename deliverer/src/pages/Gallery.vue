<script setup lang="ts">
import type { ReviewSummary } from '@/lib/types';

const lib = useLibrary();
const fm = useFormats();
const { t } = useI18n();
/** images the Smart deletion criteria would flag today, per character (coreflame/trash.py) */
const review = ref<ReviewSummary | null>(null);

onMounted(async () => {
  await lib.loadWatches();
  try {
    review.value = await api.get<ReviewSummary>('/api/gallery/review');
  } catch {
    review.value = null;
  }
});

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
    <div v-if="review?.total" class="review">
      <Icon name="scan" :size="13" class="rose" />
      <span>
        {{
          $t('gallery.review.title', {
            n: fm.number(review.total),
            score: review.min_score.toFixed(2),
            characters: $t(
              'gallery.review.characters',
              { n: review.characters.length },
              review.characters.length,
            ),
          })
        }}
      </span>
      <RouterLink
        v-for="c in review.characters.slice(0, 3)"
        :key="c.slug"
        :to="{ path: `/gallery/${c.slug}`, query: { delete: 'smart' } }"
        class="chip"
      >
        {{ $t('gallery.review.each', { label: c.label, n: fm.number(c.count) }) }}
      </RouterLink>
      <div class="spacer" />
      <RouterLink
        :to="{ path: `/gallery/${review.characters[0]!.slug}`, query: { delete: 'smart' } }"
        class="btn sm gh"
      >
        {{ $t('gallery.review.review') }}
      </RouterLink>
    </div>
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
/* the quiet card: what Smart would flag, a link into each character with Smart preselected */
.review {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  background: color-mix(in oklch, var(--surf) 60%, transparent);
  font-size: 12px;
  color: var(--mut);
}
.review .rose {
  color: var(--rose);
}
.review .chip {
  color: var(--tx);
}
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
