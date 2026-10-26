import NetworkCard from './NetworkCard.vue';
import { mountWithPlugins } from '@/test/utils';
import { speed } from '@/test/network';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

describe('NetworkCard', () => {
  it('shows the download figure, the quality word and the latency', () => {
    const w = mountWithPlugins(NetworkCard);
    const net = useNetwork();
    net.speed = speed();
    return nextTick().then(() => {
      expect(w.text()).toContain('73.1');
      expect(w.text()).toContain('Mbps');
      expect(w.text()).toContain('good · 30 ms');
      expect(w.findAll('.bars i.lit')).toHaveLength(3);
    });
  });

  it('reads "Checking…" before the first answer', () => {
    const w = mountWithPlugins(NetworkCard);
    expect(w.text()).toContain('Checking…');
    expect(w.text()).toContain('measuring download');
    expect(w.findAll('.bars i.lit')).toHaveLength(0);
  });

  it('a slow or thin line is degraded: ember bars and an ember second line', async () => {
    const w = mountWithPlugins(NetworkCard);
    useNetwork().speed = speed({ download_mbps: 4.2, latency_ms: 480 });
    await nextTick();
    expect(w.text()).toContain('4.2');
    expect(w.text()).toContain('poor · 480 ms');
    expect(w.find('.bars.ember').exists()).toBe(true);
    expect(w.find('.l2.ember').exists()).toBe(true);
  });

  it('an interface without a route reads "No internet" and counts down to the next probe', async () => {
    const w = mountWithPlugins(NetworkCard);
    const net = useNetwork();
    net.speed = speed({ online: false, download_mbps: null, latency_ms: null });
    net.nextAt = net.clock + 12_000;
    await nextTick();
    expect(w.text()).toContain('No internet');
    expect(w.text()).toContain('Curio-5G connected · retrying 12 s');
    expect(w.findAll('.bars i.lit')).toHaveLength(0);
    expect(w.find('.netcard.noInternet').exists()).toBe(true);
  });

  it('no interface at all reads "Disconnected" with the wifi-off glyph', async () => {
    const w = mountWithPlugins(NetworkCard);

    useNetwork().speed = speed({
      online: false,
      download_mbps: null,
      connection: { interface: null, ssid: null, isp: null, asn: null },
    });

    await nextTick();
    expect(w.text()).toContain('Disconnected');
    expect(w.text()).toContain('no network · pixiv & X unreachable');
    expect(w.find('.bars').exists()).toBe(false);
    expect(w.find('svg.off').exists()).toBe(true);
  });

  it('the ⓘ opens the detail modal', async () => {
    const w = mountWithPlugins(NetworkCard, { pinia: { stubActions: true } });
    await w.find('button[aria-label="Network details"]').trigger('click');
    expect(useNetwork().show).toHaveBeenCalled();
  });
});
