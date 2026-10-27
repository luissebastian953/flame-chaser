import type { GalleryArtist } from '@/lib/types';

/**
 * One artist across the gallery's filters: the `source:artist_id` key the
 * daemon narrows a grid with (`artist=`), a selection list with
 * (`sel_artist=`), and the chip rows key by. Shared by the filter row
 * (components/LabelFilter.vue) and By tag (pages/CharacterDetail.vue).
 */
export function artistKey(a: Pick<GalleryArtist, 'source' | 'artist_id'>): string {
  return `${a.source}:${a.artist_id}`;
}
