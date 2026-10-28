import { mount } from '@vue/test-utils';
import EmberField from './EmberField.vue';

describe('EmberField', () => {
  it('burns while active: the source line and the embers', () => {
    const wrapper = mount(EmberField, { props: { active: true } });

    expect(wrapper.find('.embers').classes()).not.toContain('out');
    expect(wrapper.findAll('.p').length).toBeGreaterThan(0);
  });

  it('stays dark when it mounts stopped', () => {
    const wrapper = mount(EmberField, { props: { active: false } });

    expect(wrapper.find('.embers').classes()).toContain('out');
    expect(wrapper.findAll('.p')).toHaveLength(0);
  });

  it('on pause the whole field fades out, then empties so nothing keeps animating', async () => {
    vi.useFakeTimers();
    const wrapper = mount(EmberField, { props: { active: true } });
    await wrapper.setProps({ active: false });

    expect(wrapper.find('.embers').classes()).toContain('out');
    expect(wrapper.findAll('.p').length).toBeGreaterThan(0);

    await vi.advanceTimersByTimeAsync(2500);
    expect(wrapper.findAll('.p')).toHaveLength(0);

    await wrapper.setProps({ active: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(wrapper.findAll('.p').length).toBeGreaterThan(0);
    vi.useRealTimers();
  });
});
