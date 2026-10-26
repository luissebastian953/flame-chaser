/**
 * While By tag (stores/deletion.ts) is on, the grid floats the images the
 * picked chips stand for to the front, keeping the grid's own order on both
 * sides, so what the selection is made of reads in one place instead of
 * being hunted across a long page. The chip rows themselves stay put - a
 * row that reshuffles under the pointer is harder to read than a long one.
 * Pure, so a test can pin it.
 */
export function pickedFirst<T>(items: readonly T[], picked: (item: T) => boolean): T[] {
  const yes: T[] = [];
  const no: T[] = [];
  for (const it of items) (picked(it) ? yes : no).push(it);
  return [...yes, ...no];
}
