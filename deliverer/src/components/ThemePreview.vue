<script setup lang="ts">
/**
 * Settings › Theme's Live preview: a header band and a gallery card drawn
 * with the DRAFT theme. The draft's CSS variables are set on this root only,
 * so the component classes inside (.panel, .btn, .chip, .phead) render the
 * draft while the rest of the app keeps the applied theme. Over live
 * artwork: the first characters' covers, gradient tiles until there are any.
 */
const theme = useTheme();
const lib = useLibrary();

const covers = computed(() =>
  lib.watches
    .filter((w) => w.cover_sha)
    .slice(0, 4)
    .map((w) => mediaUrl(w.cover_sha!)),
);

const first = computed(() => lib.watches[0] ?? null);

const style = computed(() => ({
  ...theme.draftVars,
  '--plate-blur': '0px', // the preview blurs its own band, not what is behind it
}));

const fallback = ['140 70% 45%', '330 60% 50%', '200 70% 45%', '55 70% 45%'];
</script>

<template>
  <div class="preview" :class="theme.draftClasses" :style="style">
    <div class="band" :style="{ opacity: theme.draft.window.transparent ? theme.draft.window.opacity : 1 }">
      <img v-if="covers[0]" :src="covers[0]" alt="" />
      <div v-else class="ph" :style="{ '--h': fallback[0] }" />
      <div class="scanf" />
    </div>
    <div class="panel scan card">
      <div class="phead">
        <b class="nm">{{ first?.label ?? 'Ganyu' }}</b>
        <span v-if="first?.pixiv_tags[0]" class="jp">{{ first.pixiv_tags[0] }}</span>
        <div class="spacer" />
        <span class="num">
          {{ $t('settings.theme.preview.stat', { n: (first?.post_count ?? 1284).toLocaleString() }) }}
        </span>
      </div>
      <div class="tiles">
        <div v-for="i in 3" :key="i" class="tile" :class="{ sel: i === 2 }">
          <img v-if="covers[i]" :src="covers[i]" alt="" />
          <div v-else class="ph" :style="{ '--h': fallback[i] }" />
        </div>
      </div>
      <div class="bars">
        <i class="pri" />
        <i class="acc" />
      </div>
      <div class="row">
        <span class="chip on">{{ $t('gallery.detail.watching') }}</span>
        <span class="chip">{{ $t('gallery.aside.source.twitter') }}</span>
        <div class="spacer" />
        <button class="btn pri sm" type="button" tabindex="-1">{{ $t('crawl.run') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px;
  background: var(--color-bg);
  color: var(--color-tx);
  /* the draft's grid substrate */
  background-image:
    linear-gradient(oklch(1 0 0 / var(--grid-alpha)) 1px, transparent 1px),
    linear-gradient(90deg, oklch(1 0 0 / var(--grid-alpha)) 1px, transparent 1px);
  background-size: 40px 40px;
}
.band {
  position: relative;
  height: 150px;
  overflow: hidden;
  border: 1px solid var(--color-line-soft);
}
.band img,
.tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ph {
  width: 100%;
  height: 100%;
  background: linear-gradient(160deg, hsl(var(--h)) 0%, hsl(var(--h) / 0.3) 70%, transparent 100%);
}
.scanf {
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
    to bottom,
    transparent 0 2px,
    oklch(0 0 0 / var(--scan-alpha)) 2px 3px
  );
}
.card {
  --cut: 8px;
}
.nm {
  font-weight: 600;
  font-size: 13px;
}
.jp {
  font-family: var(--font-jp);
  color: var(--color-mut);
  font-size: 12px;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 12px 13px 0;
}
.tile {
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--color-surf2);
}
.tile.sel {
  box-shadow:
    0 0 0 2px var(--color-ember),
    var(--glow);
}
.bars {
  display: flex;
  height: 3px;
  margin: 12px 13px 0;
}
.bars .pri {
  flex: 4;
  background: var(--color-ember);
  box-shadow: 0 0 8px var(--color-ember);
}
.bars .acc {
  flex: 1;
  background: var(--color-cyan);
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 13px 13px;
}
</style>
