mod auth;
mod pip;
mod sidecar;
mod tray;

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

/// The rail's "Shutdown app": same path as Cmd-Q -- daemon first (layer 1 of
/// the sidecar lifecycle), then the process. A running crawl is cancelled by
/// the daemon's SIGTERM handler and marked `interrupted` on next boot.
#[tauri::command]
fn shutdown_app(app: AppHandle) {
    sidecar::shutdown(&app);
    app.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_notification::init())
        .manage(sidecar::Sidecar::default())
        .manage(tray::TrayState::default())
        .invoke_handler(tauri::generate_handler![
            sidecar::daemon_endpoint,
            auth::source_login,
            shutdown_app,
            pip::pip_supported,
            pip::pip_open,
            pip::pip_close,
            pip::pip_resize,
            pip::pip_snap,
            tray::tray_update,
            tray::show_main
        ])
        .setup(|app| {
            sidecar::spawn(app.handle())?;
            tray::setup(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Only the main window's death ends the daemon. This handler fires
            // for every window, and the `source-login` window (auth.rs) is
            // destroyed as soon as the cookies are in hand -- shutting the
            // daemon down there killed it right before the cookies were posted.
            // The mini window (pip.rs) has no life of its own either: it goes
            // with the main window.
            if window.label() == "main" && matches!(event, WindowEvent::Destroyed) {
                pip::close(window.app_handle());
                sidecar::shutdown(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build deliverer")
        .run(|app, event| {
            // Both arms matter: ExitRequested covers Cmd-Q and the tray, Exit
            // covers the paths that skip it. Layers 2 and 3 in dawnmaker cover
            // what neither can (kill -9, a panic in this process).
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                sidecar::shutdown(app);
            }
        });
}
