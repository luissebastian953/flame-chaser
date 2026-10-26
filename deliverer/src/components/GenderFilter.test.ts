import GenderFilter from './GenderFilter.vue';
import type { Gender, GenderMode } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

function mountFilter(gender: Gender, mode: GenderMode) {
  return mountWithPlugins(GenderFilter, { props: { gender, mode } });
}

const chip = (w: ReturnType<typeof mountFilter>, text: string) =>
  w.findAll('button').find((b) => b.text() === text)!;

describe('GenderFilter', () => {
  it('Both: no Full/Partial choice, and says it is off', () => {
    const w = mountFilter('any', 'full');

    expect(w.findAll('button').map((b) => b.text())).toEqual(['Both', 'Female', 'Male']);
    expect(chip(w, 'Both').attributes('aria-pressed')).toBe('true');
    expect(w.text()).toContain('off - keep every character, any gender');
    expect(w.text()).not.toContain('467 MB');
  });

  it('a gender adds Full/Partial, explains the rule plainly, and names the cost', () => {
    const w = mountFilter('female', 'partial');

    expect(chip(w, 'Partial').attributes('aria-pressed')).toBe('true');
    expect(w.text()).toContain('2 girls + 1 boy stays, 1 girl + 1 boy does not');
    expect(w.text()).toContain('a 467 MB model downloads on first use');
  });

  it('clicking emits the new gender and mode', async () => {
    const w = mountFilter('any', 'full');
    await chip(w, 'Male').trigger('click');
    expect(w.emitted('update:gender')).toEqual([['male']]);

    const w2 = mountFilter('male', 'full');
    await chip(w2, 'Partial').trigger('click');
    expect(w2.emitted('update:mode')).toEqual([['partial']]);
  });
});
