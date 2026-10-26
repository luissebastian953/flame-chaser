/**
 * The only file that knows how to reach dawnmaker.
 *
 * Endpoint discovery: inside Tauri, `invoke("daemon_endpoint")` returns the
 * {port, token} the shell read from the sidecar's stdout handshake. In plain
 * `vite dev` there is no shell, so VITE_DAEMON_URL / VITE_DAEMON_TOKEN stand in.
 *
 * Every request carries the bearer token. EventSource cannot set headers, so
 * /api/events alone accepts ?token= -- the daemon enforces that scope.
 */
export interface Endpoint {
  base: string;
  token: string;
}

let endpoint: Endpoint | null = null;

export async function discover(): Promise<Endpoint> {
  if (endpoint) return endpoint;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const e = await invoke<{ port: number; token: string }>('daemon_endpoint');
    endpoint = { base: `http://127.0.0.1:${e.port}`, token: e.token };
  } catch {
    const base = import.meta.env.VITE_DAEMON_URL;
    const token = import.meta.env.VITE_DAEMON_TOKEN;
    if (!base || !token) {
      throw new Error('no daemon endpoint: not inside Tauri and VITE_DAEMON_URL/TOKEN unset');
    }
    endpoint = { base, token };
  }
  return endpoint;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const e = await discover();

  const res = await fetch(e.base + path, {
    method,
    headers: {
      Authorization: `Bearer ${e.token}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } }).error ?? {};
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? res.statusText);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};

/**
 * Absolute URL for a daemon path an <img> will load. Only the image routes
 * (/api/media/*, /api/preview/*) and /api/events accept ?token=.
 */
export function authedUrl(path: string): string {
  if (!endpoint) throw new Error('discover() first');
  return `${endpoint.base}${path}?token=${encodeURIComponent(endpoint.token)}`;
}

/** Absolute URL for an <img src>; the daemon serves thumbs with immutable caching. */
export function mediaUrl(sha: string, kind: 'thumb' | 'full' = 'thumb'): string {
  if (!endpoint) throw new Error('discover() first');
  // <img> cannot send Authorization either; media routes take ?token= like /events.
  return `${endpoint.base}/api/media/${sha}/${kind}?token=${encodeURIComponent(endpoint.token)}`;
}

// ---------------------------------------------------------------- SSE
export interface DaemonEvent {
  id: number;
  type: string;
  data: Record<string, unknown>;
}

/**
 * Subscribe to /api/events. EventSource reconnects on its own and re-sends
 * Last-Event-ID, so a drop mid-crawl replays what was missed from the
 * daemon's ring buffer. Returns an unsubscribe function.
 */
export function subscribe(onEvent: (ev: DaemonEvent) => void, types: string[] = TYPES): () => void {
  let es: EventSource | null = null;
  let closed = false;

  discover().then((e) => {
    if (closed) return;
    es = new EventSource(`${e.base}/api/events?token=${encodeURIComponent(e.token)}`);
    for (const t of types) {
      es.addEventListener(t, (raw) => {
        const m = raw as MessageEvent<string>;
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(m.data);
        } catch {
          /* keepalive or malformed frame */
        }
        onEvent({ id: Number(m.lastEventId), type: t, data });
      });
    }
  });

  return () => {
    closed = true;
    es?.close();
  };
}

export const TYPES = [
  'job.queued',
  'job.started',
  'job.stage',
  'job.progress',
  'job.item',
  'job.log',
  'job.finished',
  'pipeline.paused',
  'rate.budget',
  'library.media',
];
