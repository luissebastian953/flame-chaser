/**
 * Shared test helpers. `mountWithPlugins` is what every component test
 * should use: it installs a testing Pinia (real actions unless told
 * otherwise) and the real i18n instance, so templates render the English
 * strings from src/locales/en and assertions can target what the user sees.
 */
import { mount, type ComponentMountingOptions } from '@vue/test-utils';
import { createTestingPinia, type TestingOptions } from '@pinia/testing';
import type { Component } from 'vue';
import { i18n } from '@/i18n';

/**
 * Several stores branch on `'__TAURI_INTERNALS__' in window` at state
 * creation time, so flip this BEFORE the first `useX()` of a test.
 */
export function setTauri(on: boolean) {
  const w = window as unknown as Record<string, unknown>;
  if (on) w.__TAURI_INTERNALS__ = {};
  else delete w.__TAURI_INTERNALS__;
}

type Options<T> = ComponentMountingOptions<T> & { pinia?: TestingOptions };

export function mountWithPlugins<T extends Component>(component: T, options: Options<T> = {}) {
  const { pinia, global: g, ...rest } = options;

  return mount(component, {
    ...rest,
    global: {
      ...g,
      plugins: [createTestingPinia({ stubActions: false, ...pinia }), i18n, ...(g?.plugins ?? [])],
    },
  });
}
