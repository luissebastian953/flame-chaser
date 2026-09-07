mod auth;
mod sidecar;

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
        .manage(sidecar::Sidecar::default())
        .invoke_handler(tauri::generate_handler![
            sidecar::daemon_endpoint,
            auth::source_login,
            shutdown_app
        ])
        .setup(|app| {
            sidecar::spawn(&app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::Destroyed) {
                sidecar::shutdown(&window.app_handle());
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
