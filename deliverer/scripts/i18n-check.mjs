// i18n guard, part of `pnpm check`:
//  1. every static t('ns.key') / $t('ns.key') in src/ resolves in en
//  2. no bare English text nodes or attribute literals remain in templates
//  3. (warning) en keys nothing references -- probably dead, maybe dynamic
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = new URL('../src/', import.meta.url).pathname;
const walk = (d) =>
  readdirSync(d).flatMap((f) => {
    const p = join(d, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });

// --- en message tree, flattened
const en = {};
for (const f of readdirSync(join(root, 'locales/en'))) {
  const ns = f.replace(/\.json$/, '');
  const flat = (o, pre) => {
    for (const [k, v] of Object.entries(o)) {
      if (v && typeof v === 'object') flat(v, `${pre}.${k}`);
      else en[`${pre}.${k}`] = v;
    }
  };
  flat(JSON.parse(readFileSync(join(root, 'locales/en', f), 'utf8')), ns);
}

const files = walk(root).filter((p) => /\.(vue|ts)$/.test(p) && !p.endsWith('.d.ts'));
const used = new Set();
const problems = [];

for (const p of files) {
  const rel = relative(root, p);
  const src = readFileSync(p, 'utf8');

  // 1. static keys: t('a.b'), $t('a.b'), keypath="a.b", and any 'a.b' literal
  //    that names an en key (tab tables, status maps). Must resolve.
  for (const m of src.matchAll(/\$?\bt\(\s*'([\w.-]+)'/g)) {
    used.add(m[1]);
    if (!(m[1] in en)) problems.push(`${rel}: missing en key '${m[1]}'`);
  }
  for (const m of src.matchAll(/keypath="([\w.-]+)"/g)) {
    used.add(m[1]);
    if (!(m[1] in en)) problems.push(`${rel}: missing en key '${m[1]}'`);
  }
  for (const m of src.matchAll(/'([a-z]+(?:\.[\w-]+)+)'/g)) if (m[1] in en) used.add(m[1]);
  // template-literal keys t(`a.b.${x}`) -> every child of the prefix counts as used
  for (const m of src.matchAll(/`([\w.-]+)\.\$\{/g)) {
    for (const k of Object.keys(en)) if (k.startsWith(m[1] + '.')) used.add(k);
  }

  // 2. leftover literals in templates
  const tpl = /<template>([\s\S]*)<\/template>/.exec(src)?.[1];
  if (!tpl) continue;
  // attribute literals first (before they are stripped for the text-node pass);
  // an identifier-shaped value (no spaces: PHPSESSID, auth_token, an example id) is data, not prose
  const isProse = (v) => /\s/.test(v.trim()) || /^[A-Z][a-z]+$/.test(v.trim());
  for (const m of tpl.matchAll(/\s(placeholder|title|aria-label|alt)="([^"]*[A-Za-z]{3,}[^"]*)"/g)) {
    if (isProse(m[2])) problems.push(`${rel}: literal ${m[1]}="${m[2].slice(0, 60)}"`);
  }
  const stripped = tpl
    .replace(/\{\{[\s\S]*?\}\}/g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/="[^"]*"/g, '=""'); // attribute values never count as text nodes
  for (const m of stripped.matchAll(/>([^<]*[A-Za-z]{3,}[^<]*)</g)) {
    const text = m[1].trim();
    if (text && isProse(text)) problems.push(`${rel}: literal text "${text.slice(0, 60)}"`);
  }
}

const unused = Object.keys(en).filter((k) => !used.has(k));
if (unused.length)
  console.warn(`i18n: ${unused.length} en key(s) not referenced statically:\n  ${unused.join('\n  ')}`);
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log(`i18n: ${used.size} keys used, all resolve; no literal text in templates`);
