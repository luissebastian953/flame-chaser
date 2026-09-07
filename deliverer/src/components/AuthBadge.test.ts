import AuthBadge from './AuthBadge.vue';
import { mountWithPlugins } from '@/test/utils';

describe('AuthBadge', () => {
  it('shows the authenticated state as plain text, not a button', () => {
    const w = mountWithPlugins(AuthBadge, { props: { state: 'on' } });

    expect(w.text()).toContain('Authenticated');
    expect(w.find('button').exists()).toBe(false);
    expect(w.find('.badge').classes()).toContain('ok');
  });

  it('renders a connect button that emits `connect` when not authenticated', async () => {
    const w = mountWithPlugins(AuthBadge, { props: { state: 'off' } });
    const btn = w.get('button');

    expect(btn.text()).toContain('Authentication required');
    expect(btn.attributes('title')).toBe('Connect this source');
    await btn.trigger('click');
    expect(w.emitted('connect')).toHaveLength(1);
  });

  it('says so when the session expired', async () => {
    const w = mountWithPlugins(AuthBadge, { props: { state: 'expired' } });
    const btn = w.get('button');

    expect(btn.text()).toContain('Session expired');
    expect(btn.attributes('title')).toBe('Session expired — reconnect');
    await btn.trigger('click');
    expect(w.emitted('connect')).toHaveLength(1);
  });
});
