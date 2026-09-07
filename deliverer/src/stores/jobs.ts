import type { Job } from '@/lib/types';

const LOG_CAP = 400;

export const useJobs = defineStore('jobs', {
  state: () => ({
    jobs: [] as Job[],
    events: [] as DaemonEvent[],
    unsubscribe: null as null | (() => void),
  }),
  getters: {
    running: (s) => s.jobs.find((j) => j.state === 'running') ?? null,
    queued: (s) => s.jobs.filter((j) => j.state === 'queued'),
    recent: (s) => s.jobs.filter((j) => !['queued', 'running'].includes(j.state)).slice(0, 10),
  },
  actions: {
    async load() {
      this.jobs = await api.get<Job[]>('/api/jobs?limit=50');
    },
    async submit(type: string, params: Record<string, unknown> = {}) {
      const r = await api.post<{ job_id: string }>('/api/jobs', { type, params });
      await this.load();
      return r.job_id;
    },
    async cancel(id: string) {
      await api.post(`/api/jobs/${id}/cancel`);
      await this.load();
    },
    listen() {
      if (this.unsubscribe) return;

      this.unsubscribe = subscribe((ev) => {
        this.events.push(ev);
        if (this.events.length > LOG_CAP) this.events.splice(0, this.events.length - LOG_CAP);
        // job list is the source of truth; refresh it on lifecycle edges
        if (ev.type === 'job.started' || ev.type === 'job.finished' || ev.type === 'job.stage') {
          this.load().catch(() => {});
        } else if (ev.type === 'job.progress') {
          const j = this.jobs.find((x) => x.id === ev.data.job_id);
          if (j) {
            j.done = Number(ev.data.done ?? j.done);
            j.total = (ev.data.total as number | null) ?? null;
          }
        }
      });
    },
  },
});
