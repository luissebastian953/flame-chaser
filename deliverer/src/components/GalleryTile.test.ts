import GalleryTile from './GalleryTile.vue';
import type { GalleryItem } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  mediaUrl: (sha: string, kind = 'thumb') => `http://d/${sha}/${kind}`,
}));

function item(over: Partial<GalleryItem> = {}): GalleryItem {
  return {
    sha256: 'sha1',
    source: 'pixiv',
    external_id: '1',
    idx: 0,
    width: 3,
    height: 4,
    posted_at: null,
    artist_name: 'a',
    title: 't',
    thumb_url: '',
    kind: 'illustration',
    identity: 'pending',
    origin: 'pending',
    origin_by: null,
    ...over,
  };
}

function mountTile(it: GalleryItem | null, select = false) {
  return mountWithPlugins(GalleryTile, { props: { sha: 'sha1', item: it, select } });
}

describe('GalleryTile corner marks', () => {
  it('marks an AI-made image with AI; hand-drawn and unjudged ones carry nothing', () => {
    expect(
      mountTile(item({ origin: 'ai', origin_by: 'tags' }))
        .find('.xb.ai')
        .text(),
    ).toBe('AI');

    expect(
      mountTile(item({ origin: 'human', origin_by: 'declared' }))
        .find('.xb.ai')
        .exists(),
    ).toBe(false);

    expect(
      mountTile(item({ origin: 'pending' }))
        .find('.xb.ai')
        .exists(),
    ).toBe(false);

    expect(mountTile(null).find('.xb.ai').exists()).toBe(false);
  });

  it('shows the X mark beside the AI mark for an AI-made image from X', () => {
    const w = mountTile(item({ source: 'twitter', origin: 'ai', origin_by: 'model' }));

    expect(w.findAll('.marks .xb').map((b) => b.text())).toEqual(['AI', 'X']);
  });

  it('hides the AI mark in select mode, where the checkbox lives; the X mark stays', () => {
    const w = mountTile(item({ source: 'twitter', origin: 'ai', origin_by: 'model' }), true);

    expect(w.find('.xb.ai').exists()).toBe(false);
    expect(w.findAll('.marks .xb').map((b) => b.text())).toEqual(['X']);
    expect(w.find('.cb').exists()).toBe(true);
  });

  it('opens on click', async () => {
    const w = mountTile(item());
    await w.trigger('click');

    expect(w.emitted('open')).toHaveLength(1);
  });
});
