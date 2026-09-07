//! Sidecar lifecycle. Three layers, because one is not enough:
//!   1. this file  -- kill the managed child on window destroy / app exit
//!   2. dawnmaker    -- heartbeat timeout, covers kill -9 and Rust panics
//!   3. dawnmaker    -- lockfile, so a second launch attaches instead of racing
//!                    the first over the same SQLite file
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{path::BaseDirectory, AppHandle, Manager};

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
        let raw = std::env::var("REAVER_DEV_CMD")
            .unwrap_or_else(|_| "python -m dawnmaker".into());
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

/// Spawn and block until the daemon prints its handshake line:
///   DAWNMAKER_READY {"port":51234,"token":"...","pid":8123}
/// The token travels over the stdout pipe because that pipe is private to this
/// process -- argv is visible in `ps`, and a file is readable by anything.
pub fn spawn(app: &AppHandle) -> Result<Endpoint, String> {
    let mut cmd = command_for(app)?;
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
    let json = line
        .strip_prefix("DAWNMAKER_READY ")
        .ok_or_else(|| format!("unexpected first line from dawnmaker: {line}"))?;
    let endpoint: Endpoint = serde_json::from_str(json.trim())
        .map_err(|e| format!("bad handshake: {e}"))?;

    let state = app.state::<Sidecar>();
    *state.child.lock().unwrap() = Some(child);
    *state.endpoint.lock().unwrap() = Some(endpoint.clone());
    Ok(endpoint)
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
