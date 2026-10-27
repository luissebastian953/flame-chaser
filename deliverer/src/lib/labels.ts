import type { ImageLabel } from '@/lib/types';

/**
 * The one badge an image carries (GalleryItem.label): the daemon picks it when
 * several would apply, the UI only renders it. Shared by the filter row, the
 * grid tile and the aside's dropdown.
 */

/** the filter's options and the dropdown's, in control order */
export const IMAGE_LABELS: ImageLabel[] = ['ai', 'non_illust', 'unidentified'];

/** the i18n leaf under `gallery.label.` (and `gallery.label.desc.`) for each label; `none` for null */
export const LABEL_KEY: Record<ImageLabel, string> = {
  ai: 'ai',
  non_illust: 'nonIllust',
  unidentified: 'unidentified',
};

export function labelKey(label: ImageLabel | null): string {
  return label ? LABEL_KEY[label] : 'none';
}
