<script setup lang="ts">
import type { Watch } from '@/lib/types';

const lib = useLibrary();
const { t } = useI18n();
const jobs = useJobs();
const router = useRouter();
const editing = ref<Watch | null>(null);
const isNew = ref(false);
const status = reactive({ msg: '' });

onMounted(() => lib.loadWatches());

function add() {
  editing.value = {
    slug: '',
    label: '',
    pixiv_tags: [],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv', 'twitter'],
  };

  isNew.value = true;
}

function edit(w: Watch) {
  editing.value = {
    ...w,
    pixiv_tags: [...w.pixiv_tags],
    match_terms: [...w.match_terms],
    sources: [...(w.sources ?? ['pixiv', 'twitter'])],
  };

  isNew.value = false;
}

async function saved(w: Watch, runNow: boolean) {
  const r = await lib.saveWatch(w, isNew.value);
  status.msg = r.reopened ? t('crawl.status.reopened', { n: r.reopened }) : t('crawl.status.saved');
  editing.value = null;
  if (runNow) await run(w.slug);
}

async function run(slug?: string) {
  await jobs.submit('poll', slug ? { watches: [slug] } : {});
  router.push('/pipeline');
}
</script>

<template>
  <div class="top">
    <div>
      <div class="h1">{{ $t('crawl.title') }}</div>
      <div class="sub">
        {{
          $t('crawl.subtitle', {
            characters: lib.watches.length,
            tags: lib.watches.reduce((n, w) => n + w.pixiv_tags.length, 0),
          })
        }}
      </div>
    </div>
    <div class="spacer" />
    <span v-if="status.msg" class="kv">{{ status.msg }}</span>
    <button class="btn gh" @click="add">{{ $t('crawl.addCharacter') }}</button>
    <button class="btn pri" :disabled="!lib.watches.length" @click="run()">{{ $t('crawl.runAll') }}</button>
  </div>
  <div class="body">
    <div class="panel">
      <div class="phead">
        <span class="ptitle">{{ $t('crawl.table.heading') }}</span>
      </div>
      <table v-if="lib.watches.length">
        <thead>
          <tr>
            <th>{{ $t('crawl.table.character') }}</th>
            <th>{{ $t('crawl.table.sources') }}</th>
            <th>{{ $t('crawl.table.pixivTags') }}</th>
            <th>{{ $t('crawl.table.matchTerms') }}</th>
            <th>{{ $t('crawl.table.bookmarks') }}</th>
            <th>{{ $t('crawl.table.r18') }}</th>
            <th>{{ $t('crawl.table.posts') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in lib.watches" :key="w.slug">
            <td>
              <b>{{ w.label || w.slug }}</b>
              <div class="kv mono">{{ w.slug }}</div>
            </td>
            <td style="white-space: nowrap">
              <span
                class="chip"
                :class="w.sources.includes('pixiv') ? 'on' : 'off'"
                style="margin-right: 4px"
              >
                {{ $t('crawl.table.sourcePixiv') }}
              </span>
              <span class="chip" :class="w.sources.includes('twitter') ? 'on' : 'off'">
                {{ $t('crawl.table.sourceX') }}
              </span>
            </td>
            <td>
              <span v-for="tag in w.pixiv_tags" :key="tag" class="chip jp" style="margin-right: 4px">
                {{ tag }}
              </span>
            </td>
            <td>
              <span v-for="term in w.match_terms" :key="term" class="chip mono" style="margin-right: 4px">
                {{ term }}
              </span>
            </td>
            <td class="num">{{ w.min_bookmarks }}</td>
            <td>{{ w.include_r18 ? $t('crawl.table.r18On') : $t('crawl.table.r18Off') }}</td>
            <td class="num">{{ w.post_count ?? 0 }}</td>
            <td style="text-align: right; white-space: nowrap">
              <button class="btn gh sm" @click="edit(w)">{{ $t('crawl.edit') }}</button>
              <button class="btn gh sm" @click="run(w.slug)">{{ $t('crawl.run') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">{{ $t('crawl.empty') }}</div>
    </div>
  </div>
  <WatchForm v-if="editing" :watch="editing" :is-new="isNew" @save="saved" @close="editing = null" />
</template>
