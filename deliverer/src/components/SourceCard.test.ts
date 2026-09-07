import { flushPromises } from '@vue/test-utils';
import SourceCard from './SourceCard.vue';
import type { SourcesStatus } from '@/lib/types';
import { mountWithPlugins, setTauri } from '@/test/utils';

function status(
  over: { pixiv?: Partial<SourcesStatus['pixiv']>; twitter?: Partial<SourcesStatus['twitter']> } = {},
) {
  return {
    pixiv: { authed: false, user_id: null, verified: null, checked_at: null, error: null, ...over.pixiv },
    twitter: { authed: false, gallery_dl: true, cookies_file: false, from_browser: null, ...over.twitter },
    network: { resolver: 'system', proxy: false },
  } satisfies SourcesStatus;
}

function mountCard(source: 'pixiv' | 'twitter' | 'other', s: SourcesStatus | null) {
  const w = mountWithPlugins(SourceCard, {
    props: { source },
    pinia: { stubActions: true, initialState: { sources: { status: s } } },
  });

  return { w, src: useSources() };
}

const buttons = (w: ReturnType<typeof mountCard>['w']) => w.findAll('button').map((b) => b.text());

describe('SourceCard state chips (pixiv)', () => {
  it('connected: chip with the user id, Check + Sign out', () => {
    const { w } = mountCard('pixiv', status({ pixiv: { authed: true, verified: true, user_id: '42' } }));

    expect(w.text()).toContain('connected');
    expect(w.text()).toContain('user 42');
    expect(w.get('.card').classes()).toContain('on');
    expect(buttons(w)).toEqual(['Check', 'Sign out']);
  });

  it('expired: chip and Sign in again', () => {
    const { w } = mountCard('pixiv', status({ pixiv: { authed: true, verified: false } }));

    expect(w.text()).toContain('session expired');
    expect(buttons(w)).toEqual(['Sign in again']);
  });

  it('pending: stored · checking chip, no Sign in', () => {
    const { w } = mountCard('pixiv', status({ pixiv: { authed: true, verified: null } }));

    expect(w.text()).toContain('stored · checking');
    expect(buttons(w)).toEqual(['Check', 'Sign out']);
  });

  it('off: no chip, just Sign in', () => {
    const { w } = mountCard('pixiv', status());

    expect(w.find('.chip').exists()).toBe(false);
    expect(buttons(w)).toEqual(['Sign in']);
  });

  it('Check and Sign out call the store', async () => {
    const { w, src } = mountCard('pixiv', status({ pixiv: { authed: true, verified: true } }));
    const [check, signOut] = w.findAll('button');
    await check!.trigger('click');
    await signOut!.trigger('click');

    expect(src.verifyPixiv).toHaveBeenCalledTimes(1);
    expect(src.disconnect).toHaveBeenCalledWith('pixiv');
  });
});

describe('SourceCard (X)', () => {
  it('shows the browser the cookies came from', () => {
    const { w } = mountCard('twitter', status({ twitter: { authed: true, from_browser: 'firefox' } }));

    expect(w.text()).toContain('connected');
    expect(w.text()).toContain('via firefox');
    expect(buttons(w)).toEqual(['Sign out']); // no Check for X
  });
});

describe('SourceCard (other)', () => {
  it('is a disabled "coming soon" row', () => {
    const { w } = mountCard('other', status());

    expect(w.text()).toContain('coming soon');
    expect(w.get('.card').classes()).toContain('soon');
    expect(w.find('button').exists()).toBe(false);
  });
});

describe('SourceCard sign-in', () => {
  it('desktop: Sign in opens the shell login window', async () => {
    setTauri(true);
    const { w, src } = mountCard('pixiv', status());
    await w.get('button').trigger('click');

    expect(src.connectViaWindow).toHaveBeenCalledWith('pixiv');
    expect(w.find('.paste').exists()).toBe(false);
  });

  it('browser mode: Sign in reveals the note, the paste form is one more click away', async () => {
    const { w, src } = mountCard('pixiv', status());

    expect(w.find('.paste').exists()).toBe(false);
    await w.get('button').trigger('click');

    expect(src.connectViaWindow).not.toHaveBeenCalled();
    expect(w.find('.paste').exists()).toBe(true);
    expect(w.text()).toContain('browser mode');
    expect(w.text()).toContain("opens pixiv's own login page");
    expect(w.find('input').exists()).toBe(false);

    await w.get('button.link').trigger('click');
    expect(w.find('input').exists()).toBe(true);
    expect(w.text()).toContain('PHPSESSID');
  });

  it('browser mode: the pasted cookie is handed to submit()', async () => {
    const { w, src } = mountCard('pixiv', status());
    vi.mocked(src.submit).mockResolvedValue(undefined);
    await w.get('button').trigger('click');
    await w.get('button.link').trigger('click');
    await w.get('input').setValue('42_secret');
    await w.get('button.btn.pri.sm').trigger('click');

    expect(src.submit).toHaveBeenCalledWith('pixiv', { PHPSESSID: '42_secret' });
    await flushPromises();
    expect(w.find('.paste').exists()).toBe(false); // folded away on success
  });

  it('browser mode: a rejected cookie shows the error inline', async () => {
    const { w, src } = mountCard('pixiv', status());
    vi.mocked(src.submit).mockRejectedValue(new Error('session rejected'));
    await w.get('button').trigger('click');
    await w.get('button.link').trigger('click');
    await w.get('input').setValue('bad');
    await w.get('button.btn.pri.sm').trigger('click');
    await flushPromises();

    expect(w.find('.paste').exists()).toBe(true);
    expect(w.get('.err').text()).toBe('session rejected');
  });
});
