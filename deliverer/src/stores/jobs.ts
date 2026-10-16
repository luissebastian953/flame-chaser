import type { Job, Lane, PipelineState } from '@/lib/types';

/** a worker and the job on it (null = idle) */
export interface WorkerJob {
  lane: Lane;
  job: Job | null;
}

const LOG_CAP = 400;

function isToday(iso: string | null, now = new Date()): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  return (
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  );
}

export const useJobs = defineStore('jobs', {
  state: () => ({
    jobs: [] as Job[],
    events: [] as DaemonEvent[],
    pipeline: null as PipelineState | null,
    /** the worker last opened in detail; its card is the focused one in the list */
    focus: null as Lane | null,
    unsubscribe: null as null | (() => void),
  }),
  getters: {
    /** one per busy worker (pixiv, then X) */
    running: (s) => s.jobs.filter((j) => j.state === 'running'),
    /** in the order the workers will take them */
    queued: (s) =>
      s.jobs
        .filter((j) => j.state === 'queued')
        .sort((a, b) => a.position - b.position || a.created_at.localeCompare(b.created_at)),
    recent: (s) => s.jobs.filter((j) => !['queued', 'running'].includes(j.state)).slice(0, 10),
    /** finished since midnight, newest first */
    completedToday: (s) =>
      s.jobs
        .filter((j) => !['queued', 'running'].includes(j.state) && isToday(j.finished_at))
        .sort((a, b) => (b.finished_at ?? '').localeCompare(a.finished_at ?? '')),
    /** the daemon's worker lanes, in order; the two sources until it answers */
    lanes: (s): Lane[] => s.pipeline?.workers.map((w) => w.lane) ?? ['pixiv', 'twitter'],
    /**
     * One slot per worker with the job it is running. The daemon says which
     * (`/api/pipeline`); failing that the job's own `worker`/`lane`; a running
     * job that names neither (an `any` job, an older daemon) takes the first
     * free slot -- so the list and the detail always agree on where a job is.
     */
    slots(): WorkerJob[] {
      const taken = new Set<string>();
      const running = this.running;

      const out: WorkerJob[] = this.lanes.map((lane) => {
        const id = this.pipeline?.workers.find((w) => w.lane === lane)?.job_id;

        const job =
          (id ? this.jobs.find((j) => j.id === id) : null) ??
          running.find((j) => !taken.has(j.id) && (j.worker ?? j.lane) === lane) ??
          null;

        if (job) taken.add(job.id);
        return { lane, job };
      });

      for (const j of running) {
        const free = out.find((s) => !s.job);
        if (taken.has(j.id) || !free) continue;
        free.job = j;
        taken.add(j.id);
      }
      return out;
    },
    /** today's totals across every job that started today, running ones included */
    session: (s) => {
      const out = { images: 0, checked: 0, dupes: 0, dropped: 0 };
      for (const j of s.jobs) {
        if (!isToday(j.started_at)) continue;
        const c = j.counters ?? {};
        out.images += c.downloaded ?? c.stored ?? 0;
        out.checked += c.listed ?? 0;
        out.dupes += c.dupes ?? c.dupe ?? 0;
        out.dropped += c.rejected ?? 0;
      }
      return out;
    },
  },
  actions: {
    async load() {
      this.jobs = await api.get<Job[]>('/api/jobs?limit=100');
    },
    async loadPipeline() {
      this.pipeline = await api.get<PipelineState>('/api/pipeline');
    },
    /** the job on a worker's slot, else the last one that worker ran */
    forWorker(lane: Lane): Job | null {
      const now = this.slots.find((s) => s.lane === lane)?.job;
      if (now) return now;
      const onSlots = new Set(this.slots.map((s) => s.job?.id));
      return this.jobs.find((j) => !onSlots.has(j.id) && (j.worker ?? j.lane) === lane) ?? null;
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
    /** every running and queued job */
    async cancelAll() {
      const live = [...this.running, ...this.queued];
      await Promise.all(live.map((j) => api.post(`/api/jobs/${j.id}/cancel`).catch(() => {})));
      await this.load();
    },
    async pauseJob(id: string, paused: boolean) {
      await api.post(`/api/jobs/${id}/pause`, { paused });
      await this.load();
    },
    async pauseQueue(paused: boolean) {
      await api.post('/api/pipeline/pause', { paused });
      await this.loadPipeline();
    },
    async runNow(id: string) {
      await api.post(`/api/jobs/${id}/run-now`);
      await this.load();
    },
    async reorder(ids: string[]) {
      await api.post('/api/jobs/reorder', { ids });
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
        } else if (ev.type === 'job.item' && typeof ev.data.action === 'string') {
          // the daemon tallies item actions into counters too; mirror it live
          const j = this.jobs.find((x) => x.id === ev.data.job_id);
          if (j) j.counters = { ...j.counters, [ev.data.action]: (j.counters[ev.data.action] ?? 0) + 1 };
        }
      });
    },
  },
});
