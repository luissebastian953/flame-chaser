/**
 * Chip rows while By tag (stores/deletion.ts) is on: the chips already
 * picked move to the front of their row, keeping the row's own order among
 * themselves, so what the selection is made of reads in one place instead of
 * being hunted across a long row. Pure, so a test can pin it.
 */
export function pickedFirst<T>(items: readonly T[], picked: (item: T) => boolean): T[] {
  const yes: T[] = [];
  const no: T[] = [];
  for (const it of items) (picked(it) ? yes : no).push(it);
  return [...yes, ...no];
}
