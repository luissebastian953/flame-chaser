import { flushPromises } from '@vue/test-utils';
import InfoTip from './InfoTip.vue';
import { mountWithPlugins } from '@/test/utils';

describe('InfoTip', () => {
  it('is a labelled (i) button, closed until asked', () => {
    const w = mountWithPlugins(InfoTip, {
      props: { label: 'What is this?' },
      slots: { default: '<p>plain words</p>' },
      attachTo: document.body,
    });

    const trigger = w.get('button');
    expect(trigger.find('svg.icon').exists()).toBe(true); // the info icon, hidden from readers
    expect(trigger.find('svg.icon').attributes('aria-hidden')).toBe('true');
    expect(trigger.attributes('aria-label')).toBe('What is this?');
    expect(trigger.attributes('type')).toBe('button'); // never submits a form it sits in
    expect(document.body.textContent).not.toContain('plain words');
    w.unmount();
  });

  it('opens on keyboard focus, portalled to <body> so a modal cannot clip it', async () => {
    const w = mountWithPlugins(InfoTip, {
      props: { label: 'What is this?' },
      slots: { default: '<p>plain words</p>' },
      attachTo: document.body,
    });

    await w.get('button').trigger('focus');
    await flushPromises();

    const tip = document.body.querySelector('.rk-tooltip');
    expect(tip?.textContent).toContain('plain words');
    expect(w.element.contains(tip)).toBe(false);
    w.unmount();
  });
});
