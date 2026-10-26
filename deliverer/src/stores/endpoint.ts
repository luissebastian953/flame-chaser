import type { Health } from '@/lib/types';

export const useEndpoint = defineStore('endpoint', {
  state: () => ({
    ready: false,
    error: null as string | null,
    health: null as Health | null,
  }),
  actions: {
    async boot() {
      try {
        await discover();
        this.health = await api.get<Health>('/api/health');
        this.ready = true;
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
      }
    },
    async refresh() {
      this.health = await api.get<Health>('/api/health');
    },
  },
});
