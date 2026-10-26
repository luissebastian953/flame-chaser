import type { ViewerItem } from '@/lib/related';

export type Zoom = 'fit' | 'one' | 'two';

/**
 * The fullscreen image viewer (components/ImageViewer.vue), mounted once at
 * the app root over everything including the rail. The detail panel hands it
 * the related set and an index; stepping inside the viewer moves the panel
 * too, so closing returns to whatever image is current.
 *
 * With a single image in the set, ← → hand over to `stepOut`, which the
 * character page sets to walk the grid in its current order; the new post's
 * set then arrives through `replace()`.
 */
export const useViewer = defineStore('viewer', {
  state: () => ({
    open: false,
    items: [] as ViewerItem[],
    index: 0,
    zoom: 'fit' as Zoom,
    /** which end of the next set to land on after a step out of a one-image set */
    edge: null as 'first' | 'last' | null,
    stepOut: null as ((dir: 1 | -1) => void) | null,
  }),
  getters: {
    current: (s): ViewerItem | null => s.items[s.index] ?? null,
    total: (s) => s.items.length,
  },
  actions: {
    show(items: ViewerItem[], index = 0) {
      this.items = items;
      this.index = Math.min(Math.max(index, 0), Math.max(items.length - 1, 0));
      this.zoom = 'fit';
      this.edge = null;
      this.open = true;
    },
    /** A new set while open (the panel moved to another post). */
    replace(items: ViewerItem[]) {
      const at = this.edge === 'last' ? items.length - 1 : 0;
      this.items = items;
      this.index = Math.max(at, 0);
      this.zoom = 'fit';
      this.edge = null;
    },
    close() {
      this.open = false;
      this.edge = null;
    },
    go(index: number) {
      if (index < 0 || index >= this.items.length) return;
      this.index = index;
      this.zoom = 'fit';
    },
    step(dir: 1 | -1) {
      if (this.items.length <= 1) {
        this.edge = dir > 0 ? 'first' : 'last';
        this.stepOut?.(dir);
        return;
      }
      this.go((this.index + dir + this.items.length) % this.items.length);
    },
    setZoom(z: Zoom) {
      this.zoom = z;
    },
    /** Space / double-click: fit ↔ 1:1 */
    toggleZoom() {
      this.zoom = this.zoom === 'fit' ? 'one' : 'fit';
    },
  },
});
