import StatCard from './StatCard.vue';
import { mountWithPlugins } from '@/test/utils';

describe('StatCard', () => {
  it('renders its content in a panel card', () => {
    const w = mountWithPlugins(StatCard, { slots: { default: '<b>+38</b>' } });
    expect(w.find('.panel.card').text()).toBe('+38');
    expect(w.find('.decorated').exists()).toBe(false);
  });

  it('decoratedBorder adds the corner marks', () => {
    const w = mountWithPlugins(StatCard, { props: { decoratedBorder: true } });
    expect(w.find('.statcard').classes()).toContain('decorated');
  });
});
