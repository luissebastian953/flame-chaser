/**
 * Icon names are plain strings (the set is data, assets/icons/icons.json), so
 * vue-tsc cannot catch a typo -- a wrong name would just render nothing. This
 * reads every template and checks each name it uses exists in the set.
 */
const sources = import.meta.glob('/src/**/*.vue', { query: '?raw', import: 'default', eager: true });

function namesUsed(): Map<string, string> {
  const used = new Map<string, string>(); // name -> first file using it
  for (const [file, src] of Object.entries(sources) as [string, string][]) {
    // static <Icon name="x"> (a bound :name= is an expression, checked through the
    // table it reads from), and `icon: 'x'` entries of tables like Settings' tabs.
    // Quoted attribute values are skipped whole: `v-if="n > 0"` holds a `>`.
    const tag = /<Icon\b(?:[^>"]|"[^"]*")*?\sname="([^"]+)"/g;
    const found = [...src.matchAll(tag), ...src.matchAll(/\bicon: '([a-z-]+)'/g)];
    for (const m of found) if (!used.has(m[1]!)) used.set(m[1]!, file);
  }

  return used;
}

describe('the Curio icon set', () => {
  it('loads all 88 icons, each with path data', () => {
    expect(ICON_PATHS.size).toBe(88);
    for (const [name, paths] of ICON_PATHS) expect(paths.length, name).toBeGreaterThan(0);
  });

  it('every icon name used in a template exists in the set', () => {
    const used = namesUsed();
    expect(used.size).toBeGreaterThan(10); // the scan actually finds them
    const missing = [...used].filter(([name]) => !ICON_PATHS.has(name));
    expect(missing).toEqual([]);
  });
});
