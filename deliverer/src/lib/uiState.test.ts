import { applyUiState, collectUiState } from './uiState';

describe('uiState', () => {
  it('collects every curio.* key, parsed, and leaves other keys alone', () => {
    localStorage.setItem('curio.theme.v3', JSON.stringify({ preset: 'graphite' }));
    localStorage.setItem('curio.locale', 'ja');
    localStorage.setItem('vite-ui-theme', 'dark');
    expect(collectUiState()).toEqual({ 'curio.theme.v3': { preset: 'graphite' }, 'curio.locale': 'ja' });
  });

  it('writes a collected state back verbatim and counts what landed', () => {
    const n = applyUiState({ 'curio.formats.v1': { hour12: true }, 'curio.locale': 'en', junk: 1 });
    expect(n).toBe(2);
    expect(JSON.parse(localStorage.getItem('curio.formats.v1')!)).toEqual({ hour12: true });
    expect(localStorage.getItem('curio.locale')).toBe('en');
    expect(localStorage.getItem('junk')).toBeNull();
  });
});
