describe('useCharacterDefaults', () => {
  it('starts with no gender filter', () => {
    expect(useCharacterDefaults().$state).toEqual({
      gender: 'any',
      gender_mode: 'full',
      kind_filter: true,
    });
  });

  it('remembers a choice, and ignores a corrupt one', () => {
    useCharacterDefaults().set({ gender: 'female', gender_mode: 'partial' });
    useCharacterDefaults().set({ kind_filter: false });

    expect(JSON.parse(localStorage.getItem('curio.character.defaults') ?? '{}')).toEqual({
      gender: 'female',
      gender_mode: 'partial',
      kind_filter: false,
    });

    setActivePinia(createPinia());
    expect(useCharacterDefaults().gender).toBe('female');
    expect(useCharacterDefaults().kind_filter).toBe(false);

    setActivePinia(createPinia());
    localStorage.setItem('curio.character.defaults', JSON.stringify({ gender: 'girls' }));
    expect(useCharacterDefaults().gender).toBe('any');
    expect(useCharacterDefaults().kind_filter).toBe(true);
  });
});
