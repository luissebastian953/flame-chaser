import { flushPromises } from '@vue/test-utils';
import ThemePanel from './ThemePanel.vue';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
  mediaUrl: (sha: string) => `/media/${sha}`,
}));

const button = (w: ReturnType<typeof mountWithPlugins>, text: string) =>
  w.findAll('button').find((b) => b.text() === text)!;

describe('ThemePanel', () => {
  it('lists the presets and drafts the clicked one without applying it', async () => {
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();
    expect(w.text()).toContain('Nightglass');
    expect(w.text()).toContain('Bloodline');

    await w
      .findAll('.preset')
      .find((b) => b.text().includes('Bloodline'))!
      .trigger('click');

    expect(theme.draft.theme.basedOn).toBe('bloodline');
    expect(theme.applied.theme.basedOn).toBe('nightglass');
    expect(w.text()).toContain('unapplied changes');
  });

  it('a typed hex reaches the draft only once it is complete', async () => {
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();
    const input = w.find('#theme-primary');

    await input.setValue('#4a');
    expect(theme.draft.theme.primary).toBe('#e279de');
    await input.setValue('4ADE80');
    expect(theme.draft.theme.primary).toBe('#4ade80');
  });

  it('corners and glow are segmented choices', async () => {
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();
    await button(w, 'round').trigger('click');
    await button(w, 'neon').trigger('click');

    expect(theme.draft.theme).toMatchObject({ corners: 'round', glow: 'neon' });
  });

  it('export copies the JSON; import loads a pasted theme', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: write } });
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();

    await button(w, 'Export JSON').trigger('click');
    await flushPromises();
    expect(JSON.parse(write.mock.calls[0]![0] as string).basedOn).toBe('nightglass');
    expect(w.text()).toContain('copied to the clipboard');

    await button(w, 'import json').trigger('click');
    await w.find('textarea').setValue(JSON.stringify({ primary: '#ffb02e' }));
    await button(w, 'Load').trigger('click');
    expect(theme.draft.theme.primary).toBe('#ffb02e');
    expect(w.find('textarea').exists()).toBe(false);
  });

  it('save as preset adds a user preset that can be removed', async () => {
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();
    await w.find('#theme-name').setValue('Midnight ember');
    await button(w, 'Save as preset').trigger('click');

    expect(w.text()).toContain('Midnight ember');
    expect(theme.userPresets).toHaveLength(1);
    await w.find('[aria-label="Remove preset"]').trigger('click');
    expect(theme.userPresets).toHaveLength(0);
  });

  it('the preview draws the draft, not the applied theme', async () => {
    const w = mountWithPlugins(ThemePanel);
    const theme = useTheme();
    theme.draft.theme.primary = '#4ade80';
    await flushPromises();

    expect((w.find('.preview').element as HTMLElement).style.getPropertyValue('--color-ember')).toBe(
      '#4ade80',
    );

    expect(w.text()).toContain('Nightglass · solid');
    theme.draft.window = { transparent: true, opacity: 0.68, blur: true, blurPx: 12 };
    await flushPromises();
    expect(w.text()).toContain('68% · blur 12');
  });
});
