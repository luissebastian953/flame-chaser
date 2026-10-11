describe('useCharacterDefaults', () => {
  it('starts with no gender filter', () => {
    expect(useCharacterDefaults().$state).toEqual({ gender: 'any', gender_mode: 'full' });
  });

  it('remembers a choice, and ignores a corrupt one', () => {
    useCharacterDefaults().set('female', 'partial');

    expect(JSON.parse(localStorage.getItem('curio.character.defaults') ?? '{}')).toEqual({
      gender: 'female',
      gender_mode: 'partial',
    });

    setActivePinia(createPinia());
    expect(useCharacterDefaults().gender).toBe('female');

    setActivePinia(createPinia());
    localStorage.setItem('curio.character.defaults', JSON.stringify({ gender: 'girls' }));
    expect(useCharacterDefaults().gender).toBe('any');
  });
});
