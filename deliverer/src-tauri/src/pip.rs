//! The pipeline mini window: a small always-on-top panel the main window
//! opens while it is unfocused and a worker runs, and closes when it is
//! focused again or the queue empties.
//!
//! Created on demand and *closed*, never hidden: a hidden WebView keeps its
//! memory, a closed one gives it back, and the 1.5 s delay before opening
//! already covers the re-create cost. It loads `pip.html` -- a second Vite
//! entry with no Vue, no router, no store -- and gets everything it shows
//! over `pipeline:tick` events from the main window. It never reaches the
//! daemon: it has no token and does not need one.
//!
//! Placement is drag-and-snap: the user drags the panel anywhere, and on
//! release `pip_snap` slides it to the nearer left or right edge of the
//! monitor it is on, keeping the dropped height. The main window persists
//! the side and the height and hands them back on the next open.

use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{
    webview::WebviewBuilder, window::WindowBuilder, AppHandle, LogicalPosition, LogicalSize,
    Manager, Monitor, WebviewUrl, Window,
};

pub const LABEL: &str = "pip";
/// The panel's width; its height follows the row count (`pip_resize`).
const WIDTH: f64 = 280.0;
const MIN_HEIGHT: f64 = 120.0;
/// Gap between the panel and the screen edge once snapped.
const INSET: f64 = 12.0;
const SNAP_MS: u64 = 220;
const SNAP_FRAMES: u32 = 14;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Left,
    Right,
}

/// Where the panel sits: a side, and a height in logical px from the top of
/// the monitor's work area (`None` = bottom).
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct Placement {
    pub side: Side,
    pub y: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Support {
    pub supported: bool,
    pub reason: Option<&'static str>,
}

/// Wayland has no always-on-top and silently ignores `set_position`, so the
/// window would neither float nor snap. `GDK_BACKEND=x11` (XWayland) works.
pub fn is_wayland() -> bool {
    std::env::var("XDG_SESSION_TYPE")
        .map(|v| v == "wayland")
        .unwrap_or(false)
        && std::env::var("GDK_BACKEND")
            .map(|v| v != "x11")
            .unwrap_or(true)
}

#[tauri::command]
pub fn pip_supported() -> Support {
    if is_wayland() {
        Support {
            supported: false,
            reason: Some("wayland"),
        }
    } else {
        Support {
            supported: true,
            reason: None,
        }
    }
}

/// The work area of a monitor in logical px: (left, top, width, height).
fn work_area(m: &Monitor) -> (f64, f64, f64, f64) {
    let s = m.scale_factor();
    let wa = m.work_area();
    (
        wa.position.x as f64 / s,
        wa.position.y as f64 / s,
        wa.size.width as f64 / s,
        wa.size.height as f64 / s,
    )
}

/// The monitor the main window is on, else the primary one.
fn monitor_for(app: &AppHandle) -> Option<Monitor> {
    let main = app.get_webview_window("main")?;
    main.current_monitor()
        .ok()
        .flatten()
        .or_else(|| main.primary_monitor().ok().flatten())
}

/// Top-left for a placement on a monitor, clamped inside its work area.
fn place(m: &Monitor, p: Placement, height: f64) -> LogicalPosition<f64> {
    let (left, top, w, h) = work_area(m);
    let x = match p.side {
        Side::Left => left + INSET,
        Side::Right => left + w - WIDTH - INSET,
    };
    let max_y = (h - height - INSET).max(INSET);
    let y = p.y.unwrap_or(max_y).clamp(INSET, max_y);
    LogicalPosition::new(x, top + y)
}

/// Open the panel at a placement. A no-op (returns `false`) on Wayland or
/// when it is already open. Async on purpose: creating a window from a sync
/// command deadlocks on Windows.
///
/// The window is built bare and hidden, re-classed and flagged on the main
/// thread (`prepare`), and only then gets its WebView (`add_child`) and is
/// shown (`reveal`). The order matters: WebKit observes its window through
/// KVO from the moment the view is installed, and KVO pins the object's
/// class -- swapping it afterwards made the panel's close throw inside
/// `removeObserver:` and abort the app. The three steps queue on the event
/// loop in order, so the WebView lands in the panel's final class.
#[tauri::command]
pub async fn pip_open(app: AppHandle, placement: Placement, height: f64) -> Result<bool, String> {
    if is_wayland() || app.get_webview_window(LABEL).is_some() {
        return Ok(false);
    }
    let height = height.max(MIN_HEIGHT);
    let Some(m) = monitor_for(&app) else {
        return Err("no monitor".into());
    };
    let pos = place(&m, placement, height);

    #[allow(unused_mut)]
    let mut builder = WindowBuilder::new(&app, LABEL)
        .title("Curio")
        .inner_size(WIDTH, height)
        .position(pos.x, pos.y)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .focused(false)
        .resizable(false)
        .shadow(false)
        .visible(false);
    // macOS has no taskbar entry for a child window anyway; the call is a
    // no-op there but logs a warning.
    #[cfg(not(target_os = "macos"))]
    {
        builder = builder.skip_taskbar(true);
    }
    let w = builder.build().map_err(|e| e.to_string())?;
    let win = w.clone();
    w.run_on_main_thread(move || prepare(&win))
        .map_err(|e| e.to_string())?;
    // the same label as the window keeps it a WebviewWindow for `get_webview_window`
    w.add_child(
        WebviewBuilder::new(LABEL, WebviewUrl::App("pip.html".into()))
            .transparent(true)
            .focused(false)
            .auto_resize(),
        LogicalPosition::new(0.0, 0.0),
        LogicalSize::new(WIDTH, height),
    )
    .map_err(|e| e.to_string())?;
    let win = w.clone();
    w.run_on_main_thread(move || reveal(&win))
        .map_err(|e| e.to_string())?;
    Ok(true)
}

/// Over every Space / virtual desktop, full-screen apps included. The
/// builder's `visible_on_all_workspaces` covers workspaces on X11 (`stick`)
/// and the desktops of macOS, but another app's full-screen window owns a
/// Space that a regular app's NSWindow never joins, whatever its collection
/// behaviour says: only a *non-activating panel* does (`panel`). Windows
/// virtual desktops pin every app window to the desktop it was born on, while
/// a *tool window* (no taskbar or Alt-Tab presence) is not tracked and shows
/// on all of them. All of this is read when the window is first ordered in,
/// so it is set here on the hidden, still empty window. Main thread only.
fn prepare(w: &Window) {
    #[cfg(target_os = "macos")]
    {
        use objc2::{runtime::AnyObject, ClassType};
        use objc2_app_kit::{NSWindow, NSWindowCollectionBehavior, NSWindowStyleMask};
        if let Ok(ptr) = w.ns_window() {
            // SAFETY: a live NSWindow that tao owns for the panel's lifetime,
            // read and set on the main thread as AppKit requires. Re-classing
            // it is sound while the panel class is no larger than the object
            // tao allocated (NSPanel adds no ivars; checked, not assumed) and
            // nothing has observed it yet -- the WebView comes after.
            let obj: &AnyObject = unsafe { &*(ptr as *const AnyObject) };
            let cls = panel::CurioPanel::class();
            if cls.instance_size() <= obj.class().instance_size() {
                unsafe { AnyObject::set_class(obj, cls) };
            }
            let ns: &NSWindow = unsafe { &*(ptr as *const NSWindow) };
            ns.setStyleMask(ns.styleMask() | NSWindowStyleMask::NonactivatingPanel);
            ns.setCollectionBehavior(
                ns.collectionBehavior()
                    | NSWindowCollectionBehavior::CanJoinAllSpaces
                    | NSWindowCollectionBehavior::FullScreenAuxiliary,
            );
            ns.setHidesOnDeactivate(false); // a panel's default is to hide with its app
        }
    }
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            GetWindowLongPtrW, SetWindowLongPtrW, SetWindowPos, GWL_EXSTYLE, SWP_FRAMECHANGED,
            SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, WS_EX_APPWINDOW,
            WS_EX_TOOLWINDOW,
        };
        if let Ok(h) = w.hwnd() {
            let hwnd = h.0 as windows_sys::Win32::Foundation::HWND;
            // SAFETY: style bits on a window tao owns; the frame-changed
            // SetWindowPos makes the shell re-read them.
            unsafe {
                let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
                let ex = (ex | WS_EX_TOOLWINDOW as isize) & !(WS_EX_APPWINDOW as isize);
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
                SetWindowPos(
                    hwnd,
                    std::ptr::null_mut(),
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                );
            }
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let _ = w;
}

/// Shown last, without taking focus. Main thread only.
fn reveal(w: &Window) {
    #[cfg(target_os = "macos")]
    {
        use objc2_app_kit::NSWindow;
        if let Ok(ptr) = w.ns_window() {
            // SAFETY: as in `prepare`.
            let ns: &NSWindow = unsafe { &*(ptr as *const NSWindow) };
            ns.orderFrontRegardless(); // visible on every Space, and not key: focus stays where it is
        }
    }
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{ShowWindow, SW_SHOWNOACTIVATE};
        if let Ok(h) = w.hwnd() {
            // SAFETY: a window tao owns; shown as a tool window, focus untouched.
            unsafe { ShowWindow(h.0 as windows_sys::Win32::Foundation::HWND, SW_SHOWNOACTIVATE) };
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        // X11: `stick` from the builder is all a window manager offers. A
        // focused full-screen window sits in the layer above "always on top"
        // in most WMs, so it covers the panel until it loses focus.
        let _ = w.show();
    }
}

#[tauri::command]
pub fn pip_close(app: AppHandle) {
    close(&app);
}

pub fn close(app: &AppHandle) {
    if let Some(w) = app.get_webview_window(LABEL) {
        let _ = w.close();
    }
}

/// The page asks for the height its rows need; the panel grows or shrinks in
/// place and stays inside the work area.
#[tauri::command]
pub fn pip_resize(app: AppHandle, height: f64) -> Result<(), String> {
    let Some(w) = app.get_webview_window(LABEL) else {
        return Ok(());
    };
    let height = height.max(MIN_HEIGHT);
    w.set_size(LogicalSize::new(WIDTH, height))
        .map_err(|e| e.to_string())?;
    if let (Ok(Some(m)), Ok(pos), Ok(s)) =
        (w.current_monitor(), w.outer_position(), w.scale_factor())
    {
        let (_, top, _, h) = work_area(&m);
        let y = pos.y as f64 / s - top;
        let max_y = (h - height - INSET).max(INSET);
        if y > max_y {
            let x = pos.x as f64 / s;
            let _ = w.set_position(LogicalPosition::new(x, top + max_y));
        }
    }
    Ok(())
}

/// After a drag: slide to the nearer horizontal edge of the monitor the
/// panel's centre is on, keep the dropped height, and report where it
/// landed so the main window can remember it. `reduced` = no animation.
#[tauri::command]
pub async fn pip_snap(app: AppHandle, reduced: bool) -> Result<Placement, String> {
    let Some(w) = app.get_webview_window(LABEL) else {
        return Err("no mini window".into());
    };
    let s = w.scale_factor().map_err(|e| e.to_string())?;
    let pos = w.outer_position().map_err(|e| e.to_string())?;
    let size = w.outer_size().map_err(|e| e.to_string())?;
    let (x0, y0) = (pos.x as f64 / s, pos.y as f64 / s);
    let (pw, ph) = (size.width as f64 / s, size.height as f64 / s);

    let m = w
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| w.primary_monitor().ok().flatten())
        .ok_or("no monitor")?;
    let (left, top, mw, mh) = work_area(&m);

    let side = if x0 + pw / 2.0 - left < mw / 2.0 {
        Side::Left
    } else {
        Side::Right
    };
    let max_y = (mh - ph - INSET).max(INSET);
    let y = (y0 - top).clamp(INSET, max_y);
    let target = place(&m, Placement { side, y: Some(y) }, ph);

    if reduced {
        w.set_position(target).map_err(|e| e.to_string())?;
    } else {
        let frame = Duration::from_millis(SNAP_MS / SNAP_FRAMES as u64);
        for i in 1..=SNAP_FRAMES {
            let t = i as f64 / SNAP_FRAMES as f64;
            // ease-out: fast start, settles softly
            let e = 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t);
            let x = x0 + (target.x - x0) * e;
            let yy = y0 + (target.y - y0) * e;
            w.set_position(LogicalPosition::new(x, yy))
                .map_err(|e| e.to_string())?;
            tokio::time::sleep(frame).await;
        }
    }
    Ok(Placement { side, y: Some(y) })
}

/// The class the mini window is swapped to before it is first shown. On
/// macOS a regular app's NSWindow joins every desktop Space but never another
/// app's full-screen Space, whatever its collection behaviour says -- the
/// window server lists it on the desktop alone (measured with
/// `CGSCopySpacesForWindows`); a non-activating NSPanel is listed on every
/// Space, full-screen ones included. tao builds an NSWindow, so the live
/// instance is re-classed (what tauri-nspanel does too). Tao's own method
/// overrides are kept here: a key window that never becomes main, and the
/// drag a WKWebView would otherwise swallow.
#[cfg(target_os = "macos")]
mod panel {
    use objc2::{define_class, msg_send, MainThreadOnly};
    use objc2_app_kit::{NSEvent, NSEventType, NSPanel};

    define_class!(
        #[unsafe(super(NSPanel))]
        #[thread_kind = MainThreadOnly]
        #[name = "CurioPanel"]
        pub struct CurioPanel;

        impl CurioPanel {
            /// clicks reach the panel's buttons and drag handle; being
            /// non-activating, that never brings the app forward
            #[unsafe(method(canBecomeKeyWindow))]
            fn can_become_key_window(&self) -> bool {
                true
            }

            #[unsafe(method(canBecomeMainWindow))]
            fn can_become_main_window(&self) -> bool {
                false
            }

            #[unsafe(method(sendEvent:))]
            fn send_event(&self, event: &NSEvent) {
                if event.r#type() == NSEventType::LeftMouseDown && self.isMovableByWindowBackground() {
                    self.performWindowDragWithEvent(event);
                }
                let _: () = unsafe { msg_send![super(self), sendEvent: event] };
            }
        }
    );
}
