/**
 * The two things the webview asks the desktop shell to do with the outside
 * world: open a permalink in the default browser, and show a stored file in
 * Finder / Explorer. Both go through the opener plugin; outside Tauri the
 * first falls back to a new tab and the second is not offered (the browser
 * build has no file manager to hand the path to).
 */

export async function openExternal(url: string): Promise<void> {
  try {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
  } catch {
    window.open(url, '_blank');
  }
}

/** Reveal a blob in the file manager. Desktop only (`opener:allow-reveal-item-in-dir`). */
export async function revealInFolder(path: string): Promise<void> {
  const { revealItemInDir } = await import('@tauri-apps/plugin-opener');
  await revealItemInDir(path);
}
