//! Sidecar lifecycle. Three layers, because one is not enough:
//!   1. this file  -- kill the managed child on window destroy / app exit
//!   2. dawnmaker    -- heartbeat timeout, covers kill -9 and Rust panics;
//!      the beats come from a thread in this file, never from the webview
//!   3. dawnmaker    -- lockfile, so two daemons never race over the same
//!      SQLite file: the second one reports `already_running` and leaves.
//!      If the holder is an orphan (its Curio crashed; it lives on until
//!      its heartbeat runs out), `spawn` stops it and tries again; if its
//!      Curio is alive, this launch fails instead of hijacking it
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{path::BaseDirectory, AppHandle, Manager};

const HEARTBEAT_EVERY: Duration = Duration::from_secs(5);
/// How long `spawn` keeps retrying while an orphaned daemon winds down.
const ORPHAN_WAIT: Duration = Duration::from_secs(20);
const HEARTBEAT_IO: Duration = Duration::from_secs(2);

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Endpoint {
    pub port: u16,
    pub token: String,
    pub pid: u32,
}

#[derive(Default)]
pub struct Sidecar {
    pub child: Mutex<Option<Child>>,
    pub endpoint: Mutex<Option<Endpoint>>,
}

/// In dev, run the daemon straight from the venv -- a Python edit must not
/// cost a PyInstaller rebuild. The handshake line is identical either way, so
/// nothing downstream knows the difference.
fn command_for(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let raw = std::env::var("REAVER_DEV_CMD").unwrap_or_else(|_| "python -m dawnmaker".into());
        let mut parts = raw.split_whitespace();
        let mut cmd = Command::new(parts.next().ok_or("empty REAVER_DEV_CMD")?);
        cmd.args(parts);
        Ok(cmd)
    } else {
        let exe = app
            .path()
            .resolve("sidecar/dawnmaker", BaseDirectory::Resource)
            .map_err(|e| e.to_string())?;
        Ok(Command::new(exe))
    }
}

/// What the daemon's first line said.
enum Handshake {
    Ready(Child, Endpoint),
    /// another daemon holds the lock on this db: its pid
    Busy(u32),
}

/// Start the daemon once and read its first line.
fn start(cmd: &mut Command) -> Result<Handshake, String> {
    let mut child = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to start dawnmaker: {e}"))?;

    let stdout = child.stdout.take().ok_or("no stdout on dawnmaker")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();

    // A daemon that never prints READY is a startup failure, not a hang: the
    // caller should surface it, so no unbounded wait here.
    reader.read_line(&mut line).map_err(|e| e.to_string())?;
    if let Some(json) = line.strip_prefix("DAWNMAKER_READY ") {
        let endpoint = serde_json::from_str(json.trim()).map_err(|e| format!("bad handshake: {e}"))?;
        return Ok(Handshake::Ready(child, endpoint));
    }
    let _ = child.wait(); // it printed its verdict and left
    let verdict: serde_json::Value = serde_json::from_str(line.trim())
        .map_err(|_| format!("unexpected first line from dawnmaker: {line}"))?;
    match (verdict["error"].as_str(), verdict["pid"].as_u64()) {
        (Some("already_running"), Some(pid)) => Ok(Handshake::Busy(pid as u32)),
        _ => Err(format!("unexpected first line from dawnmaker: {line}")),
    }
}

/// Whether a process has been reparented to launchd / init -- its Curio is
/// gone. Unix only; elsewhere every lock holder counts as somebody's.
fn orphan(pid: u32) -> bool {
    #[cfg(unix)]
    {
        Command::new("ps")
            .args(["-o", "ppid=", "-p", &pid.to_string()])
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| s.trim().parse::<u32>().ok())
            == Some(1)
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        false
    }
}

/// Ask a daemon to stop (its SIGTERM handler cancels the running job and
/// marks it interrupted at the next boot, as a crash would).
fn terminate(pid: u32) {
    #[cfg(unix)]
    let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status();
    #[cfg(not(unix))]
    let _ = pid;
}

/// Spawn and block until the daemon prints its handshake line:
///   DAWNMAKER_READY {"port":51234,"token":"...","pid":8123}
/// The token travels over the stdout pipe because that pipe is private to this
/// process -- argv is visible in `ps`, and a file is readable by anything.
///
/// A daemon left behind by a crash keeps the lock until its heartbeat runs
/// out (up to 45 s); launching Curio again inside that window used to fail
/// outright. Such a daemon has no parent any more, so it is stopped and the
/// spawn retried until it is gone. A daemon whose Curio is alive is left
/// alone, and this launch fails with a message instead.
pub fn spawn(app: &AppHandle) -> Result<Endpoint, String> {
    let mut cmd = command_for(app)?;
    let deadline = Instant::now() + ORPHAN_WAIT;
    let (child, endpoint) = loop {
        match start(&mut cmd)? {
            Handshake::Ready(child, endpoint) => break (child, endpoint),
            Handshake::Busy(pid) => {
                if !orphan(pid) {
                    return Err(format!("Curio is already running (its daemon is pid {pid})"));
                }
                if Instant::now() > deadline {
                    return Err(format!("the daemon of a previous Curio (pid {pid}) would not stop"));
                }
                terminate(pid);
                std::thread::sleep(Duration::from_millis(250));
            }
        }
    };

    let state = app.state::<Sidecar>();
    *state.child.lock().unwrap() = Some(child);
    *state.endpoint.lock().unwrap() = Some(endpoint.clone());

    let (app, ep) = (app.clone(), endpoint.clone());
    std::thread::Builder::new()
        .name("dawnmaker-heartbeat".into())
        .spawn(move || heartbeat(app, ep))
        .map_err(|e| e.to_string())?;
    Ok(endpoint)
}

/// Layer 2's sender. A native thread, not a webview timer: WebKit and App Nap
/// throttle a hidden window's timers far past the daemon's 30 s timeout, so a
/// `setInterval` in the page turned "Curio sat behind other windows for a
/// while" into a daemon that had exited while the window still looked alive.
/// A thread still dies with a force-quit or a panic, which is exactly what
/// the heartbeat exists to detect. Stops once `shutdown` has taken the child.
fn heartbeat(app: AppHandle, endpoint: Endpoint) {
    // Raw HTTP/1.1 over loopback: one fixed request needs no HTTP client, and
    // the token stays in this process's memory. No Origin header, so the
    // daemon's CORS rules do not apply; Host must be the one it binds.
    let request = format!(
        "POST /api/heartbeat HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\n\
         Content-Length: 0\r\nConnection: close\r\n\r\n",
        endpoint.port, endpoint.token
    );
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, endpoint.port));
    loop {
        std::thread::sleep(HEARTBEAT_EVERY);
        if app.state::<Sidecar>().child.lock().unwrap().is_none() {
            return;
        }
        // a miss is not an error to act on: the daemon either answers the
        // next one or has exited, and the UI learns that from its own calls
        let _ = beat(addr, &request);
    }
}

fn beat(addr: SocketAddr, request: &str) -> std::io::Result<()> {
    let mut s = TcpStream::connect_timeout(&addr, HEARTBEAT_IO)?;
    s.set_write_timeout(Some(HEARTBEAT_IO))?;
    s.set_read_timeout(Some(HEARTBEAT_IO))?;
    s.write_all(request.as_bytes())?;
    let mut sink = [0u8; 512];
    let _ = s.read(&mut sink); // `{"ok":true}`; nothing to do with it
    Ok(())
}

pub fn shutdown(app: &AppHandle) {
    if let Some(mut child) = app.state::<Sidecar>().child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait(); // reap, so no zombie outlives us
    }
}

#[tauri::command]
pub fn daemon_endpoint(state: tauri::State<Sidecar>) -> Result<Endpoint, String> {
    state
        .endpoint
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "dawnmaker is not running".into())
}
