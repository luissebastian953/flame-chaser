import { flushPromises } from '@vue/test-utils';
import DeleteToast from './DeleteToast.vue';
import type { DeleteToast as DeleteToastItem } from '@/stores/toasts';
import { mountWithPlugins } from '@/test/utils';

function toast(over: Partial<DeleteToastItem> = {}): DeleteToastItem {
  return {
    kind: 'delete',
    id: 1,
    slug: 'firefly',
    label: 'Firefly',
    images: 23,
    bytes: 184 * 1024 * 1024,
    forgotten: 21,
    permanent: false,
    batchId: 'b1',
    undo: vi.fn(async () => {}),
    ...over,
  };
}

function mountToast(t: DeleteToastItem) {
  return mountWithPlugins(DeleteToast, {
    props: { toast: t },
    pinia: { initialState: { toasts: { items: [t], held: false } } },
  });
}

describe('DeleteToast', () => {
  it('says what moved to trash, for whom, how much and how many posts were forgotten, and arms a 10 s timer', () => {
    const t = toast();
    const w = mountToast(t);
    const toasts = useToasts();

    expect(w.text()).toContain('23 images moved to trash');
    expect(w.text()).toContain('Firefly · 184 MiB · 21 posts forgotten');
    expect(w.find('button.act').text()).toBe('Undo');
    expect(toasts.armed(1)).toBe(true);
  });

  it('Undo restores the batch and dismisses the toast', async () => {
    const t = toast();
    const w = mountToast(t);
    const toasts = useToasts();

    await w.find('button.act').trigger('click');
    await flushPromises();
    expect(t.undo).toHaveBeenCalled();
    expect(toasts.items).toEqual([]);
  });

  it('a permanent deletion has no Undo and says deleted', () => {
    const w = mountToast(toast({ permanent: true, batchId: null, forgotten: 0 }));

    expect(w.text()).toContain('23 images deleted');
    expect(w.text()).not.toContain('forgotten');
    expect(w.find('button.act').exists()).toBe(false);
  });
});
