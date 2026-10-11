import Icon from './Icon.vue';
import { mountWithPlugins } from '@/test/utils';

describe('Icon', () => {
  it('draws the named icon from the set, decorative by default', () => {
    const w = mountWithPlugins(Icon, { props: { name: 'crawl' } });

    expect(w.findAll('path')).toHaveLength(ICON_PATHS.get('crawl')!.length);
    expect(w.attributes('width')).toBe('16');
    expect(w.attributes('stroke')).toBe('currentColor'); // follows the text colour, so the theme
    expect(w.attributes('aria-hidden')).toBe('true');
    expect(w.attributes('role')).toBeUndefined();
  });

  it('with a label it is announced as an image', () => {
    const w = mountWithPlugins(Icon, { props: { name: 'close', size: 12, label: 'Close' } });

    expect(w.attributes('role')).toBe('img');
    expect(w.attributes('aria-label')).toBe('Close');
    expect(w.attributes('aria-hidden')).toBeUndefined();
    expect(w.attributes('width')).toBe('12');
  });

  it('an unknown name draws nothing and warns in development', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const w = mountWithPlugins(Icon, { props: { name: 'no-such-icon' } });

    expect(w.findAll('path')).toHaveLength(0);
    expect(warn).toHaveBeenCalledWith('<Icon>: no icon named "no-such-icon"');
    warn.mockRestore();
  });
});
