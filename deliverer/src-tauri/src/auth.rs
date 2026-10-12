//! Source sign-in without ever seeing a password.
//!
//! `source_login` opens the site's OWN login page in a second window, waits
//! until the session cookie the crawler needs appears in that window's cookie
//! jar, closes the window and returns the cookie(s) to the webview, which
//! hands them to dawnmaker. HttpOnly cookies (PHPSESSID is one) are readable
//! through `cookies_for_url` -- verified against tauri 2.7 docs.
//!
//! The login window is NOT in `capabilities/default.json`, so remote content
//! in it has no IPC. It shares the app's cookie store, which is also why an
//! already-signed-in user gets an instant return.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

const LABEL: &str = "source-login";
const TIMEOUT: Duration = Duration::from_secs(300);
const POLL: Duration = Duration::from_millis(500);

struct Site {
    login: &'static str,
    /// URL whose cookie jar we read once the user is signed in.
    home: &'static str,
    /// Every one of these must be present before we consider it done.
    needed: &'static [&'static str],
    title: &'static str,
}

fn site(source: &str) -> Result<Site, String> {
    Ok(match source {
        "pixiv" => Site {
            login:
                "https://accounts.pixiv.net/login?return_to=https%3A%2F%2Fwww.pixiv.net%2F&lang=en",
            home: "https://www.pixiv.net/",
            needed: &["PHPSESSID"],
            title: "Sign in to pixiv — Curio",
        },
        "twitter" => Site {
            login: "https://x.com/i/flow/login",
            home: "https://x.com/",
            needed: &["auth_token", "ct0"],
            title: "Sign in to X — Curio",
        },
        other => return Err(format!("unknown source {other}")),
    })
}

fn harvest(app: &AppHandle, home: &str, needed: &[&str]) -> Option<HashMap<String, String>> {
    let win = app.get_webview_window(LABEL)?;
    let url = Url::parse(home).ok()?;
    let jar = win.cookies_for_url(url).ok()?;
    let mut out = HashMap::new();
    for c in jar {
        if needed.contains(&c.name()) {
            out.insert(c.name().to_string(), c.value().to_string());
        }
    }
    (needed.iter().all(|n| out.contains_key(*n))).then_some(out)
}

/// Async on purpose: `cookies_for_url` can deadlock in a sync command on
/// Windows, and the poll loop must not block the main thread anywhere.
#[tauri::command]
pub async fn source_login(
    app: AppHandle,
    source: String,
) -> Result<HashMap<String, String>, String> {
    let s = site(&source)?;

    // Already signed in from a previous window? Then no window at all.
    if let Some(w) = app.get_webview_window(LABEL) {
        let _ = w.close();
    }
    let url = Url::parse(s.login).map_err(|e| e.to_string())?;
    WebviewWindowBuilder::new(&app, LABEL, WebviewUrl::External(url))
        .title(s.title)
        .inner_size(520.0, 760.0)
        .resizable(true)
        .build()
        .map_err(|e| e.to_string())?;

    let started = Instant::now();
    loop {
        tokio::time::sleep(POLL).await;
        if app.get_webview_window(LABEL).is_none() {
            return Err("sign-in window closed".into());
        }
        if let Some(cookies) = harvest(&app, s.home, s.needed) {
            if let Some(w) = app.get_webview_window(LABEL) {
                let _ = w.close();
            }
            return Ok(cookies);
        }
        if started.elapsed() > TIMEOUT {
            if let Some(w) = app.get_webview_window(LABEL) {
                let _ = w.close();
            }
            return Err("sign-in timed out".into());
        }
    }
}
