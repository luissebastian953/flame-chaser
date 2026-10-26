import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import RekaResolver from 'reka-ui/resolver';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
  version: string;
};

let sha = 'dev';
try {
  sha = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
    .toString()
    .trim();
} catch {
  /* no git yet */
}

// Tauri expects a fixed port and no screen clearing (its own output matters).
export default defineConfig(({ mode }) => ({
  plugins: [
    vue(),
    tailwindcss(),
    // No import lines for the things every file uses. The generated .d.ts
    // files keep vue-tsc and the editor informed; .eslintrc-auto-import.json
    // keeps ESLint informed. All three are committed.
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia', 'vue-i18n'],
      dirs: ['src/stores', 'src/lib'],
      dts: 'src/auto-imports.d.ts',
      eslintrc: { enabled: true, filepath: './.eslintrc-auto-import.json' },
      vueTemplate: true,
    }),
    Components({
      dirs: ['src/components'],
      resolvers: [RekaResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  // tsconfig `paths` only informs vue-tsc; Vite's dev scanner needs the alias itself.
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  clearScreen: false,
  envPrefix: ['VITE_', 'TAURI_ENV_'],
  define: { __APP_VERSION__: JSON.stringify(pkg.version), __GIT_SHA__: JSON.stringify(sha) },
  // CHANGELOG.md lives at the repo root; Settings › Updates imports it as text
  server: { port: 5173, strictPort: true, host: '127.0.0.1', fs: { allow: ['..'] } },
  build: {
    target: 'es2022',
    // two pages: the app, and the pipeline mini window (src/pip/, no Vue) --
    // a second WebView that must stay a few kilobytes
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
        pip: fileURLToPath(new URL('./pip.html', import.meta.url)),
      },
    },
    // 'hidden': maps are written for local debugging but not referenced from
    // the bundle, so a release never ships the TypeScript. Minification stays on.
    sourcemap: mode === 'production' ? 'hidden' : true,
  },
  // Vitest runs through the same plugins, so auto-imports, `@/` and the
  // defines above work in tests exactly as they do in the app.
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['src/**/*.test.ts'],
    setupFiles: ['src/test/setup.ts'],
    clearMocks: true,
  },
}));
