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

    expect(jobs.running?.id).toBe('r');
    expect(jobs.queued.map((j) => j.id)).toEqual(['q1', 'q2']);
    expect(jobs.recent.map((j) => j.id)).toEqual(['s', 'f', 'c', 'i']);
  });

  it('running is null with an idle queue and recent is capped at 10', () => {
    const jobs = useJobs();
    jobs.jobs = Array.from({ length: 14 }, (_, i) => job(`d${i}`, 'succeeded'));

    expect(jobs.running).toBeNull();
    expect(jobs.queued).toEqual([]);
    expect(jobs.recent).toHaveLength(10);
    expect(jobs.recent[0]?.id).toBe('d0');
  });
});

describe('useJobs actions', () => {
  it('load() asks for the last 50 jobs', async () => {
    vi.mocked(api.get).mockResolvedValueOnce([job('a', 'queued')]);
    const jobs = useJobs();
    await jobs.load();

    expect(api.get).toHaveBeenCalledWith('/api/jobs?limit=50');
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

  it('caps the event log at 400 entries, dropping the oldest', () => {
    const { jobs, onEvent } = listenAndCapture();
    for (let i = 1; i <= 405; i++) onEvent({ id: i, type: 'job.log', data: {} });

    expect(jobs.events).toHaveLength(400);
    expect(jobs.events[0]?.id).toBe(6);
    expect(jobs.events.at(-1)?.id).toBe(405);
  });
});
