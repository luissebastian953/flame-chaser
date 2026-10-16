/**
 * What the pipeline screens derive from a job: which character it is, its
 * stage track, its counter, its worker's colour. Pure, so the list and the
 * detail state agree and a test can pin each rule.
 */
import type { Job, Lane, Watch } from '@/lib/types';

/** worker identity, not status: 1 ember, 2 moss, 3 cyan, 4 amber */
export const WORKER_COLORS = ['var(--ember)', 'var(--moss)', 'var(--cyan)', 'oklch(0.8 0.15 75)'] as const;

export function workerColor(index: number): string {
  return WORKER_COLORS[index % WORKER_COLORS.length]!;
}

/** 0-based worker index of a lane, in the daemon's worker order */
export function workerIndex(lane: Lane | null | undefined, lanes: readonly Lane[]): number {
  const i = lane ? lanes.indexOf(lane) : -1;
  return i < 0 ? 0 : i;
}

/** the source a job talks to, or null for one that sends no request */
export function sourceOf(job: Job): Lane | null {
  const src = job.params.source;
  if (src === 'pixiv' || src === 'twitter') return src;
  if (job.type === 'timelines') return 'twitter';
  if (job.type === 'link') return 'pixiv';
  return job.lane === 'any' ? null : job.lane;
}

/**
 * The engine's stages for this kind of job, in order (coreflame/pipeline.py).
 * A pixiv crawl walks discover → tags → link → download; an X crawl searches
 * (downloading as it goes) then downloads what is left.
 */
export function stagesOf(job: Job): string[] {
  const src = sourceOf(job);
  if (job.type === 'poll' && src === 'pixiv') return ['discover', 'tags', 'link', 'download'];
  if (job.type === 'poll' || job.type === 'timelines') return ['discover', 'download'];
  if (job.type === 'media') return ['download'];
  if (job.type === 'link') return ['link'];
  if (job.type === 'tags') return ['tags'];
  if (job.type === 'label') return ['label', 'people', 'identify'];
  return job.stage ? [job.stage] : [];
}

/** index of the active stage; -1 before the first; length when finished */
export function stageIndex(job: Job): number {
  const stages = stagesOf(job);
  if (job.state === 'queued') return -1;
  if (job.state !== 'running') return stages.length;
  return Math.max(0, job.stage ? stages.indexOf(job.stage) : 0);
}

export interface Character {
  slug: string | null;
  name: string;
  /** the first pixiv tag when it is not just the name again */
  jp: string | null;
  cover: string | null;
}

/** the character a job crawls; null for a job that is not about one */
export function characterOf(job: Job, watches: readonly Watch[]): Character | null {
  const slugs = job.params.watches;
  const slug = Array.isArray(slugs) && slugs.length === 1 ? String(slugs[0]) : null;
  if (!slug) return null;
  const w = watches.find((x) => x.slug === slug);
  const name = w?.label || slug;
  const jp = w?.pixiv_tags[0] ?? w?.match_terms[0] ?? null;
  const again = !!jp && jp.toLowerCase().startsWith(name.toLowerCase());
  return { slug, name, jp: jp && !again ? jp : null, cover: w?.cover_sha ?? null };
}

/** posts this run: pixiv = new artworks, X = posts kept against the target */
export function postsOf(job: Job): number {
  const c = job.counters ?? {};
  return c.posts ?? c.new ?? c.new_posts ?? 0;
}

/** the X target this run collects to; pixiv walks to its watermark instead */
export function targetOf(job: Job): number | null {
  const t = Number(job.params.target);
  return Number.isFinite(t) && t > 0 ? t : null;
}

/** "1m 45s" / "12s" / "2h 05m" */
export function elapsed(fromIso: string | null, now: number = Date.now()): string {
  if (!fromIso) return '—';
  const sec = Math.max(0, Math.floor((now - new Date(fromIso).getTime()) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}m`;
}

/** seconds left at the rate so far; null without an honest denominator */
export function etaSeconds(done: number, total: number | null, spentSec: number): number | null {
  if (total === null || done <= 0 || done >= total || spentSec <= 0) return null;
  return Math.round(((total - done) * spentSec) / done);
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

/** an event's kind in the activity feed: new (moss) · dupe (cyan) · gone (ember) · info · sys */
export function activityKind(ev: { type: string; data: Record<string, unknown> }): string {
  const action = ev.data.action;
  if (action === 'new' || action === 'stored') return 'new';
  if (action === 'dupe') return 'dupe';
  if (action === 'gone' || action === 'rejected') return 'gone';
  if (ev.type === 'job.log') return ev.data.level === 'warning' || ev.data.level === 'error' ? 'warn' : 'sys';
  return 'info';
}

/** an i18n key + params naming a job that is not about one character */
export function jobTitle(job: Job): { key: string; params: Record<string, unknown> } {
  if (job.type === 'timelines') return { key: 'pipeline.job.timelines', params: {} };
  if (job.type === 'media') return { key: 'pipeline.job.media', params: { source: sourceOf(job) ?? '' } };
  if (job.type === 'link') return { key: 'pipeline.job.link', params: {} };
  if (job.type === 'tags') return { key: 'pipeline.job.tags', params: {} };
  if (job.type === 'label') return { key: 'pipeline.job.label', params: {} };
  return { key: 'pipeline.job.other', params: { type: job.type } };
}

/** the queue row's right-hand meta: tags to search, posts to collect, accounts to read */
export function queueMeta(job: Job, watches: readonly Watch[]): { key: string; n: number } | null {
  if (job.type === 'timelines' && typeof job.params.accounts === 'number') {
    return { key: 'pipeline.meta.accounts', n: job.params.accounts };
  }
  const target = targetOf(job);
  if (target !== null) return { key: 'pipeline.meta.target', n: target };
  const ch = characterOf(job, watches);
  if (ch && sourceOf(job) === 'pixiv') {
    const w = watches.find((x) => x.slug === ch.slug);
    return { key: 'pipeline.meta.tags', n: w?.pixiv_tags.length ?? 0 };
  }
  return null;
}

/**
 * Keeps a pipeline screen live: the job list and the pipeline state every few
 * seconds (req/min and the rate budgets move without events), and a clock
 * for elapsed times. Stops when the screen unmounts.
 */
export function usePipelineLive(everyMs = 3000) {
  const jobs = useJobs();
  const now = ref(Date.now());
  let poll: ReturnType<typeof setInterval> | undefined;
  let tick: ReturnType<typeof setInterval> | undefined;
  const refresh = () => Promise.all([jobs.load(), jobs.loadPipeline()]).catch(() => {});

  onMounted(() => {
    refresh();
    poll = setInterval(refresh, everyMs);
    tick = setInterval(() => (now.value = Date.now()), 1000);
  });

  onBeforeUnmount(() => {
    clearInterval(poll);
    clearInterval(tick);
  });

  return { now, refresh };
}
