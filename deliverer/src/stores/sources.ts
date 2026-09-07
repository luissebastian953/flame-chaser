import type { SourcesStatus } from '@/lib/types';

/**
 * Source sessions. `connect()` prefers the shell's login window (Tauri opens
 * the site's own login page and reads the cookie); outside Tauri the caller
 * falls back to a paste form. The cookie goes straight to the daemon and is
 * never kept in the webview.
 */
export type Source = 'pixiv' | 'twitter';

const DISMISS_KEY = 'curio.authgate.dismissed';

export const useSources = defineStore('sources', {
  state: () => ({
    status: null as SourcesStatus | null,
    busy: null as Source | null,
    error: '' as string,
    dismissed: (() => {
      try {
        return localStorage.getItem(DISMISS_KEY) === '1';
      } catch {
        return false;
      }
    })(),
  }),
  getters: {
    /** Connected = a stored session that passed its check. Unverified is not ok. */
    pixivOk: (s) => !!s.status?.pixiv.authed && s.status.pixiv.verified === true,
    pixivPending: (s) => !!s.status?.pixiv.authed && s.status.pixiv.verified === null,
    twitterOk: (s) => !!s.status?.twitter.authed,
    anyConnected(): boolean {
      return this.pixivOk || this.twitterOk;
    },
    /** First launch gate: nothing connected and not dismissed this install. */
    needsGate(): boolean {
      return this.status !== null && !this.anyConnected && !this.dismissed;
    },
    inTauri: () => '__TAURI_INTERNALS__' in window,
  },
  actions: {
    async load() {
      this.status = await api.get<SourcesStatus>('/api/sources/status');
    },
    dismiss() {
      this.dismissed = true;
      try {
        localStorage.setItem(DISMISS_KEY, '1');
      } catch {
        /* best effort */
      }
    },
    /** Desktop: open the site's login window and read the cookie(s) back. */
    async connectViaWindow(source: Source) {
      this.busy = source;
      this.error = '';
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const cookies = await invoke<Record<string, string>>('source_login', { source });
        await this.submit(source, cookies);
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
      } finally {
        this.busy = null;
      }
    },
    /** Both modes: hand cookies to the daemon, which verifies before storing. */
    async submit(source: Source, cookies: Record<string, string>) {
      this.busy = source;
      this.error = '';
      try {
        if (source === 'pixiv') {
          this.status = await api.post<SourcesStatus>('/api/auth/pixiv', {
            php_sessid: cookies.PHPSESSID ?? cookies.php_sessid ?? '',
          });
        } else {
          this.status = await api.post<SourcesStatus>('/api/auth/twitter', {
            auth_token: cookies.auth_token ?? '',
            ct0: cookies.ct0 ?? '',
          });
        }
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
        throw e;
      } finally {
        this.busy = null;
      }
    },
    async verifyPixiv() {
      this.status = await api.post<SourcesStatus>('/api/auth/pixiv/verify');
    },
    async disconnect(source: Source) {
      await api.del(`/api/auth/${source}`);
      await this.load();
    },
  },
});
