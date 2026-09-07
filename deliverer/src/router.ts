import { createRouter, createWebHashHistory } from 'vue-router';

// Hash history: the webview serves index.html from a bundled path, so there is
// no server to rewrite deep links to it.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/gallery' },
    { path: '/gallery', component: () => import('@/pages/Gallery.vue') },
    { path: '/gallery/:slug', component: () => import('@/pages/CharacterDetail.vue'), props: true },
    { path: '/config', component: () => import('@/pages/Config.vue') },
    { path: '/pipeline', component: () => import('@/pages/Pipeline.vue') },
    { path: '/settings', component: () => import('@/pages/Settings.vue') },
  ],
});
