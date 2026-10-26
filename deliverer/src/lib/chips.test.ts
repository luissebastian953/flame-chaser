import { pickedFirst } from '@/lib/chips';

describe('pickedFirst', () => {
  it('moves the picked chips to the front and keeps the row order on both sides', () => {
    const row = ['a', 'b', 'c', 'd', 'e'];
    expect(pickedFirst(row, (x) => x === 'd' || x === 'b')).toEqual(['b', 'd', 'a', 'c', 'e']);
  });

  it('leaves a row alone when nothing is picked', () => {
    expect(pickedFirst(['a', 'b'], () => false)).toEqual(['a', 'b']);
  });
});
