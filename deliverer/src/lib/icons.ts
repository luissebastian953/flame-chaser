/**
 * The Curio icon set (assets/icons/icons.json, verbatim from curio-icons.zip):
 * 86 line icons on a 24 grid, stroked with currentColor -- so they follow the
 * theme -- with square caps and miter joins to match the cut corners. Render
 * with <Icon name="…">. To update the set, replace the JSON file.
 */
import manifest from '@/assets/icons/icons.json';

interface IconDef {
  n: string; // name
  c: string; // category
  t: string; // search tags
  d: string[]; // path data
}

/** icon name -> its path data */
export const ICON_PATHS: ReadonlyMap<string, readonly string[]> = new Map(
  (manifest as IconDef[]).map((i) => [i.n, i.d]),
);
