//! The tray (menu-bar) icon: the one "mini" surface that costs no WebView.
//! Its tooltip carries the crawl's progress; its menu pauses or resumes the
//! queue, brings the mini window back after it was hidden, and quits. A
//! left click brings the main window to the front. On Linux Wayland, where
//! the mini window cannot float, this is the only background surface.
//!
//! Labels come from the webview (`tray_update`), so the menu follows the
//! interface language; the menu is rebuilt only when a label or the paused
//! flag changes, the tooltip every time it changes.

use std::sync::Mutex;

use serde::Deserialize;
use tauri::{
    image::Image,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager,
};

use crate::sidecar;

pub const ID: &str = "main";

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
pub struct Labels {
    pub pause: String,
    pub resume: String,
    pub show_pip: String,
    pub quit: String,
}

impl Default for Labels {
    fn default() -> Self {
        Self {
            pause: "Pause all".into(),
            resume: "Resume all".into(),
            show_pip: "Show mini window".into(),
            quit: "Quit Curio".into(),
        }
    }
}

#[derive(Default)]
pub struct TrayState {
    pub labels: Mutex<Labels>,
    pub paused: Mutex<bool>,
    pub tooltip: Mutex<String>,
}

fn menu(app: &AppHandle, labels: &Labels, paused: bool) -> tauri::Result<Menu<tauri::Wry>> {
    let pause = MenuItem::with_id(
        app,
        "pause",
        if paused {
            &labels.resume
        } else {
            &labels.pause
        },
        true,
        None::<&str>,
    )?;
    let show = MenuItem::with_id(app, "show-pip", &labels.show_pip, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", &labels.quit, true, None::<&str>)?;
    Menu::with_items(
        app,
        &[&pause, &show, &PredefinedMenuItem::separator(app)?, &quit],
    )
}

/// macOS: a monochrome template image (alpha only; the system tints it for
/// light and dark menu bars). Elsewhere: the app icon as it is.
fn icon(app: &AppHandle) -> Option<Image<'static>> {
    if cfg!(target_os = "macos") {
        Image::from_bytes(include_bytes!("../icons/tray.png")).ok()
    } else {
        app.default_window_icon().cloned().map(Image::to_owned)
    }
}

pub fn focus_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    let labels = Labels::default();
    let mut builder = TrayIconBuilder::with_id(ID)
        .tooltip("Curio")
        .menu(&menu(app, &labels, false)?)
        .show_menu_on_left_click(false)
        .icon_as_template(true)
        .on_menu_event(|app, ev| match ev.id().as_ref() {
            "pause" => {
                let _ = app.emit_to("main", "tray:pause", ());
            }
            "show-pip" => {
                focus_main(app);
                let _ = app.emit_to("main", "tray:show-pip", ());
            }
            "quit" => {
                sidecar::shutdown(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, ev| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = ev
            {
                focus_main(tray.app_handle());
            }
        });
    if let Some(img) = icon(app) {
        builder = builder.icon(img);
    }
    builder.build(app)?;
    Ok(())
}

/// The webview's view of the tray: tooltip text (None keeps the current
/// one), whether the queue is paused, and the menu labels in its language.
#[tauri::command]
pub fn tray_update(
    app: AppHandle,
    state: tauri::State<TrayState>,
    tooltip: Option<String>,
    paused: bool,
    labels: Option<Labels>,
) -> Result<(), String> {
    let Some(tray) = app.tray_by_id(ID) else {
        return Ok(());
    };
    if let Some(text) = tooltip {
        let mut cur = state.tooltip.lock().map_err(|e| e.to_string())?;
        if *cur != text {
            tray.set_tooltip(Some(&text)).map_err(|e| e.to_string())?;
            *cur = text;
        }
    }
    let labels_changed = match labels {
        Some(l) => {
            let mut cur = state.labels.lock().map_err(|e| e.to_string())?;
            let changed = *cur != l;
            *cur = l;
            changed
        }
        None => false,
    };
    let paused_changed = {
        let mut cur = state.paused.lock().map_err(|e| e.to_string())?;
        let changed = *cur != paused;
        *cur = paused;
        changed
    };
    if labels_changed || paused_changed {
        let labels = state.labels.lock().map_err(|e| e.to_string())?.clone();
        let m = menu(&app, &labels, paused).map_err(|e| e.to_string())?;
        tray.set_menu(Some(m)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// The mini window or the tray asks for the main window: unminimise, show, focus.
#[tauri::command]
pub fn show_main(app: AppHandle) {
    focus_main(&app);
}
