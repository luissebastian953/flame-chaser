import type { Job } from '@/lib/types';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
  subscribe: vi.fn(() => vi.fn()),
}));

function job(id: string, state: Job['state'], over: Partial<Job> = {}): Job {
  return {
    id,
    type: 'poll_pixiv',
    params: {},
    state,
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '2026-09-06T00:00:00Z',
    started_at: null,
    finished_at: null,
    lane: 'pixiv',
    worker: null,
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

describe('useJobs getters', () => {
  it('split the list into running / queued / recent', () => {
    const jobs = useJobs();

    jobs.jobs = [
      job('r', 'running'),
      job('q1', 'queued'),
      job('q2', 'queued'),
      job('s', 'succeeded'),
      job('f', 'failed'),
      job('c', 'cancelled'),
      job('i', 'interrupted'),
    ];

    expect(jobs.running.map((j) => j.id)).toEqual(['r']);
    expect(jobs.queued.map((j) => j.id)).toEqual(['q1', 'q2']);
    expect(jobs.recent.map((j) => j.id)).toEqual(['s', 'f', 'c', 'i']);
  });

  it('running is empty with an idle queue and recent is capped at 10', () => {
    const jobs = useJobs();
    jobs.jobs = Array.from({ length: 14 }, (_, i) => job(`d${i}`, 'succeeded'));

    expect(jobs.running).toEqual([]);
    expect(jobs.queued).toEqual([]);
    expect(jobs.recent).toHaveLength(10);
    expect(jobs.recent[0]?.id).toBe('d0');
  });
});

describe('useJobs pipeline getters', () => {
  it('queued follows the queue position, not creation order', () => {
    const jobs = useJobs();

    jobs.jobs = [
      job('a', 'queued', { position: 3 }),
      job('b', 'queued', { position: -1 }),
      job('c', 'queued'),
    ];

    expect(jobs.queued.map((j) => j.id)).toEqual(['b', 'c', 'a']);
  });

  it('completedToday keeps what finished since midnight, newest first', () => {
    const now = new Date();
    const at = (h: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate(), h).toISOString();
    const jobs = useJobs();

    jobs.jobs = [
      job('early', 'succeeded', { finished_at: at(0) }),
      job('late', 'failed', { finished_at: new Date(Date.parse(at(0)) + 1000).toISOString() }),
      job('old', 'succeeded', { finished_at: '2020-01-01T00:00:00Z' }),
      job('run', 'running', { started_at: at(0) }),
    ];

    expect(jobs.completedToday.map((j) => j.id)).toEqual(['late', 'early']);
  });

  it('session sums today across finished and running jobs', () => {
    const today = new Date().toISOString();
    const jobs = useJobs();

    jobs.jobs = [
      job('a', 'succeeded', {
        started_at: today,
        counters: { downloaded: 5, listed: 40, dupes: 2, rejected: 1 },
      }),
      job('b', 'running', { started_at: today, counters: { stored: 3, listed: 10, dupe: 1 } }),
      job('c', 'succeeded', { started_at: '2020-01-01T00:00:00Z', counters: { downloaded: 99 } }),
    ];

    expect(jobs.session).toEqual({ images: 8, checked: 50, dupes: 3, dropped: 1 });
  });

  it('slots place each running job once, by the daemon, its worker, or the first free slot', () => {
    const jobs = useJobs();

    jobs.pipeline = {
      paused: false,
      pause_reason: null,
      online: true,
      workers: [
        { lane: 'pixiv', job_id: 'p' },
        { lane: 'twitter', job_id: null },
      ],
      budgets: [],
      req_per_min: 0,
    };

    jobs.jobs = [
      job('p', 'running', { worker: 'pixiv' }),
      job('o', 'running', { worker: null, lane: 'any' }),
    ];

    expect(jobs.slots.map((s) => [s.lane, s.job?.id])).toEqual([
      ['pixiv', 'p'],
      ['twitter', 'o'],
    ]);

    expect(jobs.forWorker('twitter')?.id).toBe('o'); // the detail reads the same slot
  });

  it('forWorker prefers the running job, else the last one that worker ran', () => {
    const jobs = useJobs();

    jobs.jobs = [
      job('last', 'succeeded', { worker: 'twitter' }),
      job('now', 'running', { worker: 'pixiv' }),
      job('before', 'succeeded', { worker: 'pixiv' }),
    ];

    expect(jobs.forWorker('pixiv')?.id).toBe('now');
    expect(jobs.forWorker('twitter')?.id).toBe('last');
  });
});

describe('useJobs pipeline actions', () => {
  it('pause, run-now, reorder and pause-queue hit their routes', async () => {
    vi.mocked(api.post).mockResolvedValue(undefined);
    vi.mocked(api.get).mockResolvedValue([]);
    const jobs = useJobs();
    await jobs.pauseJob('j1', true);
    await jobs.runNow('j2');
    await jobs.reorder(['j3', 'j2']);
    await jobs.pauseQueue(true);

    expect(api.post).toHaveBeenCalledWith('/api/jobs/j1/pause', { paused: true });
    expect(api.post).toHaveBeenCalledWith('/api/jobs/j2/run-now');
    expect(api.post).toHaveBeenCalledWith('/api/jobs/reorder', { ids: ['j3', 'j2'] });
    expect(api.post).toHaveBeenCalledWith('/api/pipeline/pause', { paused: true });
    expect(api.get).toHaveBeenCalledWith('/api/pipeline');
  });

  it('cancelAll cancels every running and queued job', async () => {
    vi.mocked(api.post).mockResolvedValue(undefined);
    vi.mocked(api.get).mockResolvedValue([]);
    const jobs = useJobs();
    jobs.jobs = [job('r', 'running'), job('q', 'queued'), job('s', 'succeeded')];
    await jobs.cancelAll();

    expect(api.post).toHaveBeenCalledWith('/api/jobs/r/cancel');
    expect(api.post).toHaveBeenCalledWith('/api/jobs/q/cancel');
    expect(api.post).not.toHaveBeenCalledWith('/api/jobs/s/cancel');
  });
});

describe('useJobs actions', () => {
  it('load() asks for the last 100 jobs', async () => {
    vi.mocked(api.get).mockResolvedValueOnce([job('a', 'queued')]);
    const jobs = useJobs();
    await jobs.load();

    expect(api.get).toHaveBeenCalledWith('/api/jobs?limit=100');
    expect(jobs.jobs.map((j) => j.id)).toEqual(['a']);
  });

  it('submit() posts {type, params}, reloads, and returns the id', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j9' });
    vi.mocked(api.get).mockResolvedValueOnce([job('j9', 'queued')]);
    const jobs = useJobs();
    const id = await jobs.submit('poll_pixiv', { slug: 'kiana' });

    expect(id).toBe('j9');
    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'poll_pixiv', params: { slug: 'kiana' } });
    expect(jobs.queued.map((j) => j.id)).toEqual(['j9']);
  });

  it('submitMany() returns every planned job id, and just the one from an older daemon', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'a', job_ids: ['a', 'b'] });
    vi.mocked(api.get).mockResolvedValueOnce([]);
    expect(await useJobs().submitMany('poll', { watches: ['kiana'] })).toEqual(['a', 'b']);

    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'only' });
    vi.mocked(api.get).mockResolvedValueOnce([]);
    expect(await useJobs().submitMany('poll')).toEqual(['only']);
  });

  it('submit() defaults params to an empty object', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });
    vi.mocked(api.get).mockResolvedValueOnce([]);
    await useJobs().submit('download_pending');

    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'download_pending', params: {} });
  });

  it('cancel() hits the cancel route then reloads', async () => {
    vi.mocked(api.post).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockResolvedValueOnce([job('j1', 'cancelled')]);
    const jobs = useJobs();
    await jobs.cancel('j1');

    expect(api.post).toHaveBeenCalledWith('/api/jobs/j1/cancel');
    expect(jobs.jobs[0]?.state).toBe('cancelled');
  });
});

describe('useJobs listen()', () => {
  function listenAndCapture() {
    const jobs = useJobs();
    jobs.listen();
    const onEvent = vi.mocked(subscribe).mock.calls[0]![0];
    return { jobs, onEvent };
  }

  it('subscribes once', () => {
    const jobs = useJobs();
    jobs.listen();
    jobs.listen();

    expect(subscribe).toHaveBeenCalledTimes(1);
    expect(jobs.unsubscribe).toBeTypeOf('function');
  });

  it('applies job.progress in place without a refetch', () => {
    const { jobs, onEvent } = listenAndCapture();
    jobs.jobs = [job('r', 'running', { done: 1, total: 10 })];
    onEvent({ id: 1, type: 'job.progress', data: { job_id: 'r', done: 7, total: 12 } });

    expect(jobs.jobs[0]).toMatchObject({ done: 7, total: 12 });
    expect(api.get).not.toHaveBeenCalled();
  });

  it('tallies item actions into the job counters live', () => {
    const { jobs, onEvent } = listenAndCapture();
    jobs.jobs = [job('r', 'running', { counters: { new: 2 } })];
    onEvent({ id: 1, type: 'job.item', data: { job_id: 'r', action: 'new' } });
    onEvent({ id: 2, type: 'job.item', data: { job_id: 'r', action: 'dupe' } });

    expect(jobs.jobs[0]?.counters).toEqual({ new: 3, dupe: 1 });
  });

  it('keeps an honest null total from the daemon', () => {
    const { jobs, onEvent } = listenAndCapture();
    jobs.jobs = [job('r', 'running', { done: 1, total: 10 })];
    onEvent({ id: 1, type: 'job.progress', data: { job_id: 'r', done: 2, total: null } });

    expect(jobs.jobs[0]?.total).toBeNull();
  });

  it('reloads the list on lifecycle edges', () => {
    vi.mocked(api.get).mockResolvedValue([]);
    const { onEvent } = listenAndCapture();
    onEvent({ id: 1, type: 'job.started', data: {} });
    onEvent({ id: 2, type: 'job.stage', data: {} });
    onEvent({ id: 3, type: 'job.finished', data: {} });
    onEvent({ id: 4, type: 'job.log', data: {} });

    expect(api.get).toHaveBeenCalledTimes(3);
  });

  it('refetches the pipeline when the hold changes hands, and reads an offline hold', () => {
    vi.mocked(api.get).mockResolvedValue({
      paused: true,
      pause_reason: 'offline',
      online: false,
      workers: [],
      budgets: [],
      req_per_min: 0,
    });

    const { jobs, onEvent } = listenAndCapture();
    expect(jobs.offline).toBe(false);
    onEvent({ id: 1, type: 'pipeline.paused', data: { paused: true, reason: 'offline' } });

    expect(api.get).toHaveBeenCalledWith('/api/pipeline');
    return vi.waitFor(() => expect(jobs.offline).toBe(true));
  });

  it('caps the event log at 400 entries, dropping the oldest', () => {
    const { jobs, onEvent } = listenAndCapture();
    for (let i = 1; i <= 405; i++) onEvent({ id: i, type: 'job.log', data: {} });

    expect(jobs.events).toHaveLength(400);
    expect(jobs.events[0]?.id).toBe(6);
    expect(jobs.events.at(-1)?.id).toBe(405);
  });
});
