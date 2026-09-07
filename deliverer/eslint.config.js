// ESLint 9 flat config: Vue 3 SFCs + TypeScript. Prettier owns formatting, so
// every stylistic rule is switched off here (eslint-config-prettier) and
// ESLint only reports things that are wrong, not things that are ugly.
import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript';
import prettier from 'eslint-config-prettier';
import globals from 'globals';
import stylistic from '@stylistic/eslint-plugin';
import { readFileSync } from 'node:fs';

// written by unplugin-auto-import on every dev/build run
const autoImports = JSON.parse(
  readFileSync(new URL('./.eslintrc-auto-import.json', import.meta.url), 'utf8'),
);

export default defineConfigWithVueTs(
  {
    ignores: [
      'dist/**',
      'src-tauri/**',
      'node_modules/**',
      '.build/**',
      'src/auto-imports.d.ts',
      'src/components.d.ts',
    ],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  prettier,
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...autoImports.globals,
        __APP_VERSION__: 'readonly',
        __GIT_SHA__: 'readonly',
      },
    },
    rules: {
      // the app is one team's code, not a library: short names are fine
      'vue/multi-word-component-names': 'off',
      // v-html is never used; keep the rule on so it stays that way
      'vue/no-v-html': 'error',
      // `_x` marks a deliberately unused binding
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // async handlers in templates are the norm here
      '@typescript-eslint/no-floating-promises': 'off',
      'vue/require-default-prop': 'off',
      // Prettier formats attributes; ESLint must not fight it
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
    },
  },
  {
    // Vertical rhythm -- the one formatting concern Prettier leaves alone.
    // Blank lines around functions, multi-line declarations (computed(),
    // stores) and multi-line calls (watch(), onMounted()); after the imports.
    // Single-line `const x = useX()` lines may stay grouped.
    files: ['**/*.{ts,vue}'],
    plugins: { '@stylistic': stylistic },
    rules: {
      '@stylistic/padding-line-between-statements': [
        'error',
        { blankLine: 'always', prev: 'import', next: '*' },
        { blankLine: 'any', prev: 'import', next: 'import' },
        { blankLine: 'always', prev: '*', next: 'function' },
        { blankLine: 'always', prev: 'function', next: '*' },
        { blankLine: 'always', prev: '*', next: 'multiline-const' },
        { blankLine: 'always', prev: 'multiline-const', next: '*' },
        { blankLine: 'always', prev: '*', next: 'multiline-expression' },
        { blankLine: 'always', prev: 'multiline-expression', next: '*' },
        { blankLine: 'always', prev: '*', next: ['interface', 'type'] },
        { blankLine: 'always', prev: ['interface', 'type'], next: '*' },
        { blankLine: 'always', prev: '*', next: 'export' },
        { blankLine: 'always', prev: 'export', next: '*' },
      ],
    },
  },
  {
    files: ['vite.config.ts', 'eslint.config.js', 'scripts/**/*.mjs'],
    languageOptions: { globals: globals.node },
  },
  {
    // Vitest with `globals: true`: describe/it/expect/vi need no import
    files: ['**/*.test.ts', 'src/test/**/*.ts'],
    languageOptions: { globals: globals.vitest },
  },
);
