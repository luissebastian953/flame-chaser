import LanguagePanel from '@/components/LanguagePanel.vue';
import { mountWithPlugins } from '@/test/utils';
import { setLocale } from '@/i18n';

describe('LanguagePanel', () => {
  afterEach(() => {
    localStorage.clear();
    setLocale('en');
  });

  it('lists every locale, enables only the ready ones and checks the active one', () => {
    const w = mountWithPlugins(LanguagePanel);
    const rows = w.findAll('button.lang');

    expect(rows).toHaveLength(5);
    expect(rows[0]!.text()).toContain('English');
    expect(rows[0]!.attributes('disabled')).toBeUndefined();
    expect(rows[0]!.classes()).toContain('on');
    expect(rows[0]!.text()).toContain('✓');
    expect(rows[1]!.attributes('disabled')).toBeDefined();
    expect(rows[1]!.text()).toContain('coming soon');
  });

  it('follows the system by default and unfollows when a language is picked', async () => {
    const w = mountWithPlugins(LanguagePanel);
    const follow = w.find('#follow');

    expect(follow.attributes('data-state')).toBe('checked');
    await w.find('button.lang').trigger('click');
    expect(localStorage.getItem('curio.locale')).toBe('en');
    expect(w.find('#follow').attributes('data-state')).toBe('unchecked');
  });

  it('shows coverage rows with a percentage and a live formats preview', () => {
    const w = mountWithPlugins(LanguagePanel);

    expect(w.findAll('.cov')).toHaveLength(5);
    expect(w.find('.cov .pct').text()).toBe('100%');
    expect(w.find('.cov .chip').text()).toBe('complete');
    expect(w.find('.preview').text()).toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(w.find('.preview').text()).toContain('GiB');
  });
});
