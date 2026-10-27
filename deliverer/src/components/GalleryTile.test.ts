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
    label: null,
    label_source: 'auto',
    ...over,
  };
}

function mountTile(it: GalleryItem | null, select = false) {
  return mountWithPlugins(GalleryTile, { props: { sha: 'sha1', item: it, select } });
}

describe('GalleryTile label badge', () => {
  it('shows the one label the daemon picked: AI, Non-Illust or Unidentified; none for a normal illustration', () => {
    expect(
      mountTile(item({ label: 'ai' }))
        .find('.lb')
        .text(),
    ).toBe('AI');

    expect(
      mountTile(item({ label: 'non_illust' }))
        .find('.lb')
        .text(),
    ).toBe('Non-Illust');

    expect(
      mountTile(item({ label: 'unidentified' }))
        .find('.lb')
        .text(),
    ).toBe('Unidentified');

    expect(
      mountTile(item({ label: null }))
        .find('.lb')
        .exists(),
    ).toBe(false);

    expect(mountTile(null).find('.lb').exists()).toBe(false);
  });

  it('names the tile by its label for assistive tech, and carries no name without one', () => {
    expect(mountTile(item({ label: 'ai' })).attributes('aria-label')).toBe('Image, label: AI');
    expect(mountTile(item({ label: null })).attributes('aria-label')).toBeUndefined();
  });

  it('hides the label in select mode, where the delete badge lives; the X mark stays', () => {
    const w = mountTile(item({ source: 'twitter', label: 'ai' }), true);

    expect(w.find('.lb').exists()).toBe(false);
    expect(w.findAll('.marks .xb').map((b) => b.text())).toEqual(['X']);
    expect(w.find('.cb').exists()).toBe(true);
    expect(w.attributes('aria-label')).toBe('Mark t'); // the select-mode name wins
  });

  it('the X mark is the only corner mark; a pixiv image has none', () => {
    expect(
      mountTile(item({ source: 'twitter', label: 'ai' }))
        .findAll('.marks .xb')
        .map((b) => b.text()),
    ).toEqual(['X']);

    expect(mountTile(item()).findAll('.marks .xb')).toHaveLength(0);
  });

  it('opens on click', async () => {
    const w = mountTile(item());
    await w.trigger('click');

    expect(w.emitted('open')).toHaveLength(1);
  });
});
