import type { NetworkSpeed } from '@/lib/types';

/** A healthy line, as the daemon reports it: the fixture the network store and components share. */
export function speed(over: Partial<NetworkSpeed> = {}): NetworkSpeed {
  return {
    measured_at: 1_761_500_000,
    online: true,
    testing: false,
    latency_ms: 30.3,
    download_mbps: 73.1,
    upload_mbps: 64.5,
    samples: { download: [70, 72, 73], upload: [60, 64, 64.5] },
    server: { colo: 'SIN', location: 'Singapore', ip_version: 'IPv4' },
    connection: { interface: 'wifi', ssid: 'Curio-5G', isp: 'IOH B2B', asn: 'AS4761' },
    error: null,
    ...over,
  };
}
