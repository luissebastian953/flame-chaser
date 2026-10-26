// Conventional Commits, enforced on every commit-msg (husky) and used by
// `npm run commit` (cz-git) to build the message interactively.
//
//   <type>(<scope>): <subject>
//   feat(deliverer): sign-in gate on first launch
//   fix(coreflame): probe skips fullwidth tags without a request
//
// CHANGELOG.md is written by hand for the person using the app (see
// cut-release); commit messages are for the people reading git log.
/** @type {import('cz-git').UserConfig} */
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'scope-enum': [
      2,
      'always',
      [
        'deliverer', // Tauri shell + Vue webview
        'reaver', // both Python packages, or the package root
        'coreflame', // engine
        'dawnmaker', // daemon / API
        'design', // tokens, components sheet, styles
        'docker',
        'ci',
        'release',
        'docs',
        'skills', // .claude/skills, CLAUDE.md
        'deps',
      ],
    ],
    'scope-empty': [1, 'never'], // warn, not fail: `chore: …` for cross-cutting
    'subject-case': [2, 'never', ['sentence-case', 'start-case', 'pascal-case', 'upper-case']],
    'header-max-length': [2, 'always', 100],
    'body-max-line-length': [1, 'always', 100],
  },
  prompt: {
    alias: { fd: 'docs: fix typos' },
    useEmoji: false,
    scopes: ['deliverer', 'reaver', 'coreflame', 'dawnmaker', 'design', 'docker', 'ci', 'release', 'docs', 'skills', 'deps'],
    allowCustomScopes: false,
    allowEmptyScopes: true,
    markBreakingChangeMode: true,
    types: [
      { value: 'feat', name: 'feat:     a new capability the user can see' },
      { value: 'fix', name: 'fix:      a bug fix' },
      { value: 'perf', name: 'perf:     faster or lighter, same behaviour' },
      { value: 'refactor', name: 'refactor: same behaviour, better code' },
      { value: 'style', name: 'style:    formatting only (prettier, ruff format)' },
      { value: 'test', name: 'test:     tests only' },
      { value: 'docs', name: 'docs:     docs, CLAUDE.md, skills, changelog' },
      { value: 'build', name: 'build:    bundling, PyInstaller, tauri config' },
      { value: 'ci', name: 'ci:       workflows' },
      { value: 'chore', name: 'chore:    housekeeping that fits nowhere else' },
      { value: 'revert', name: 'revert:   undo a previous commit' },
    ],
    messages: {
      type: 'Type of change:',
      scope: 'Scope (which part of the repo):',
      subject: 'Short, imperative, lowercase, no period:\n',
      body: 'Why, not what (optional; the diff shows what):\n',
      breaking: 'BREAKING CHANGE (schema, API contract, config format) - describe it:\n',
      footer: 'Issues closed, e.g. #12 (optional):\n',
      confirmCommit: 'Commit?',
    },
  },
};
