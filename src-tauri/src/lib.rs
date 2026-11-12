//! GameDevWorkstation desktop shell.
//!
//! Starts the bundled Python backend on a random free 127.0.0.1 port with a random
//! session token, hands both to the UI (`backend_info`, which waits for /health so the
//! UI shows its loading screen until then), and shuts the backend down cleanly on quit.
//! The backend also watches this process and exits if the shell crashes.

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::menu::{AboutMetadata, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Emitter, Manager, RunEvent};

struct Backend {
    port: u16,
    token: String,
    child: Mutex<Option<Child>>,
    runtime_file: PathBuf,
}

#[derive(Serialize, Clone)]
struct BackendInfo {
    port: u16,
    token: String,
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn random_token() -> String {
    let mut buf = [0u8; 24];
    if let Ok(mut f) = fs::File::open("/dev/urandom") {
        let _ = f.read_exact(&mut buf);
    }
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into()))
}

fn data_dir() -> PathBuf {
    if let Ok(p) = std::env::var("GDW_HOME") {
        return PathBuf::from(p);
    }
    if cfg!(target_os = "macos") {
        home().join("Library/Application Support/GameDevWorkstation")
    } else {
        home().join(".local/share/gamedevworkstation")
    }
}

fn logs_dir() -> PathBuf {
    if cfg!(target_os = "macos") {
        home().join("Library/Logs/GameDevWorkstation")
    } else {
        data_dir().join("logs")
    }
}

/// GET /health over a raw socket (no HTTP client dependency).
fn healthy(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_millis(800)));
    if s.write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut out = String::new();
    let _ = s.read_to_string(&mut out);
    out.starts_with("HTTP/1.1 200") || out.starts_with("HTTP/1.0 200")
}

/// Write a file only its owner can read, created 0600 from the start (no window in which it is
/// world-readable, as with write-then-chmod). An existing file is narrowed to 0600 before writing.
fn write_private(path: &std::path::Path, data: &[u8]) -> std::io::Result<()> {
    let mut opts = fs::OpenOptions::new();
    opts.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        opts.mode(0o600);
        if path.exists() {
            fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
        }
    }
    let mut f = opts.open(path)?;
    f.write_all(data)
}

fn spawn_backend(app: &AppHandle, port: u16, token: &str) -> std::io::Result<Child> {
    let logs = logs_dir();
    fs::create_dir_all(&logs)?;
    let log = fs::OpenOptions::new().create(true).append(true).open(logs.join("backend-stdout.log"))?;
    // The token goes in the environment, not the arguments: any user can read a process's
    // arguments with `ps`, only its owner can read its environment. The backend drops it from
    // its own environment once read, so its children don't inherit it.
    let args = [
        "--port".to_string(),
        port.to_string(),
        "--no-browser".to_string(),
        "--parent-pid".to_string(),
        std::process::id().to_string(),
    ];
    // Development (`cargo tauri dev`): run the backend from the repo with uv.
    let mut cmd = if let Ok(repo) = std::env::var("GDW_DEV_BACKEND") {
        let mut c = Command::new("uv");
        c.current_dir(repo).args(["run", "gamedevworkstation"]).args(&args);
        c
    } else {
        let exe = app
            .path()
            .resource_dir()
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::NotFound, e.to_string()))?
            .join("backend")
            .join("gamedevworkstation-backend");
        let mut c = Command::new(exe);
        c.args(&args);
        c
    };
    cmd.env("GDW_TOKEN", token);
    cmd.stdin(Stdio::null()).stdout(log.try_clone()?).stderr(log);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0); // own group, so quitting can stop everything it started
    }
    cmd.spawn()
}

fn stop_backend(app: &AppHandle) {
    let Some(state) = app.try_state::<Backend>() else { return };
    let mut guard = state.child.lock().unwrap();
    if let Some(mut child) = guard.take() {
        let pid = child.id() as i32;
        // SIGTERM lets the backend close PTYs, subagents, Codex CLI runs and MCP servers.
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(12) {
            if let Ok(Some(_)) = child.try_wait() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        // Anything left in its process group gets killed.
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
        let _ = child.kill();
        let _ = child.wait();
    }
    let _ = fs::remove_file(&state.runtime_file);
}

const STDOUT_LOG: &str = "backend-stdout.log";
const LOG_KEEP: usize = 3; // backend-stdout.log.1 … .3: the previous launches
const LOG_CAP_BYTES: u64 = 5 * 1024 * 1024; // a rotated log keeps at most its last 5 MB
const TAIL_LINES: usize = 40;

/// Shift `path` to `path.1` (`.1` → `.2`, …, keeping `keep`), so each launch starts a fresh log.
/// A log over `cap` bytes keeps only its last `cap` bytes when rotated.
fn rotate_log(path: &std::path::Path, keep: usize, cap: u64) {
    let len = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    if len == 0 || keep == 0 {
        return;
    }
    let numbered = |i: usize| PathBuf::from(format!("{}.{i}", path.display()));
    let _ = fs::remove_file(numbered(keep));
    for i in (1..keep).rev() {
        let _ = fs::rename(numbered(i), numbered(i + 1));
    }
    if len <= cap {
        let _ = fs::rename(path, numbered(1));
        return;
    }
    let tail = (|| -> std::io::Result<()> {
        use std::io::{Seek, SeekFrom};
        let mut f = fs::File::open(path)?;
        f.seek(SeekFrom::Start(len - cap))?;
        let mut out = fs::File::create(numbered(1))?;
        std::io::copy(&mut f, &mut out)?;
        Ok(())
    })();
    if tail.is_err() {
        let _ = fs::rename(path, numbered(1));
    } else {
        let _ = fs::remove_file(path);
    }
}

/// The last `n` lines of a log file (lossy UTF-8), for the "engine stopped" screen.
fn tail_lines(path: &std::path::Path, n: usize) -> String {
    use std::io::{Seek, SeekFrom};
    let Ok(mut f) = fs::File::open(path) else { return String::new() };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let _ = f.seek(SeekFrom::Start(len.saturating_sub(64 * 1024)));
    let mut buf = Vec::new();
    let _ = f.read_to_end(&mut buf);
    let text = String::from_utf8_lossy(&buf);
    let lines: Vec<&str> = text.lines().collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

/// Why the backend isn't there: it exited (with its code and the end of its log) or never answered.
#[derive(Serialize, Clone, Debug)]
struct BackendExit {
    kind: &'static str, // "exited" | "timeout" | "error"
    message: String,
    code: Option<i32>,
    log_path: String,
    last_lines: String,
}

impl BackendExit {
    fn new(kind: &'static str, message: String, code: Option<i32>) -> Self {
        let log = logs_dir().join(STDOUT_LOG);
        BackendExit { kind, message, code, last_lines: tail_lines(&log, TAIL_LINES), log_path: log.display().to_string() }
    }
}

/// Set once the running backend has exited on its own (cleared by restart_backend).
#[derive(Default)]
struct BackendHealth {
    exited: Mutex<Option<BackendExit>>,
}

/// Has the backend exited on its own since the last check? Reaps it, ends whatever is left of its
/// process group, and records why (once). A backend stopped by quitting isn't reported: stop_backend
/// takes the child out first.
fn poll_exit(app: &AppHandle) -> Option<BackendExit> {
    let state = app.try_state::<Backend>()?;
    let health = app.try_state::<BackendHealth>()?;
    let mut guard = state.child.lock().unwrap();
    let child = guard.as_mut()?;
    let status = match child.try_wait() {
        Ok(Some(status)) => status,
        _ => return None,
    };
    let pid = child.id() as i32;
    unsafe {
        libc::kill(-pid, libc::SIGKILL); // leftovers in its group; it can't clean up after a crash
    }
    guard.take();
    drop(guard);
    let how = match status.code() {
        Some(code) => format!("exit code {code}"),
        None => {
            #[cfg(unix)]
            {
                use std::os::unix::process::ExitStatusExt;
                status.signal().map(|s| format!("signal {s}")).unwrap_or_else(|| "unknown cause".into())
            }
            #[cfg(not(unix))]
            {
                "unknown cause".to_string()
            }
        }
    };
    let exit = BackendExit::new("exited", format!("GameDevWorkstation's engine stopped ({how})."), status.code());
    *health.exited.lock().unwrap() = Some(exit.clone());
    Some(exit)
}

/// The recorded exit, or a new one.
fn backend_exit(app: &AppHandle) -> Option<BackendExit> {
    if let Some(e) = app.try_state::<BackendHealth>().and_then(|h| h.exited.lock().unwrap().clone()) {
        return Some(e);
    }
    poll_exit(app)
}

#[tauri::command]
async fn backend_info(app: AppHandle, state: tauri::State<'_, Backend>) -> Result<BackendInfo, BackendExit> {
    let port = state.port;
    let h = app.clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<(), BackendExit> {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(90) {
            if let Some(exit) = backend_exit(&h) {
                return Err(exit); // dead: say so now instead of waiting out the 90 s
            }
            if healthy(port) {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(150));
        }
        Err(BackendExit::new(
            "timeout",
            format!("The backend didn't start. See {}", logs_dir().join(STDOUT_LOG).display()),
            None,
        ))
    })
    .await
    .map_err(|e| BackendExit::new("error", e.to_string(), None))??;
    Ok(BackendInfo { port, token: state.token.clone() })
}

/// Start the backend again after it stopped (the "engine stopped" screen's Restart). Same port and
/// token, so the UI reloads and reconnects as before. A no-op while it is still running.
#[tauri::command]
async fn restart_backend(app: AppHandle, state: tauri::State<'_, Backend>) -> Result<(), String> {
    {
        let mut guard = state.child.lock().unwrap();
        if let Some(child) = guard.as_mut() {
            if let Ok(None) = child.try_wait() {
                return Ok(());
            }
            let pid = child.id() as i32;
            unsafe {
                libc::kill(-pid, libc::SIGKILL);
            }
        }
        rotate_log(&logs_dir().join(STDOUT_LOG), LOG_KEEP, LOG_CAP_BYTES);
        let child = spawn_backend(&app, state.port, &state.token).map_err(|e| format!("Couldn't start the backend: {e}"))?;
        *guard = Some(child);
    }
    if let Some(h) = app.try_state::<BackendHealth>() {
        *h.exited.lock().unwrap() = None;
    }
    Ok(())
}

#[derive(Serialize)]
struct PowerStatus {
    on_battery: bool,
    percent: Option<u8>,
}

/// Battery state for pausing background video (WebKit has no Battery API).
#[tauri::command]
fn power_status() -> PowerStatus {
    let out = Command::new("pmset").args(["-g", "batt"]).output();
    let text = out.map(|o| String::from_utf8_lossy(&o.stdout).to_string()).unwrap_or_default();
    let on_battery = text.contains("'Battery Power'");
    let percent = text
        .split(|c: char| c == '\t' || c == ' ' || c == ';')
        .find_map(|w| w.strip_suffix('%').and_then(|n| n.parse::<u8>().ok()));
    PowerStatus { on_battery, percent }
}

/// Only same-backend API paths may be downloaded: "/api/..." with no scheme, host or
/// header-breaking characters. The backend still applies its own auth and path rules.
fn valid_api_path(path: &str) -> bool {
    path.starts_with("/api/") && !path.contains("//") && !path.chars().any(|c| c.is_whitespace() || c.is_control())
}

/// A bare file name for the save panel (no directories, no hidden-file dot).
fn clean_file_name(name: &str) -> String {
    let base = name.rsplit(['/', '\\']).next().unwrap_or("");
    let base: String = base.chars().filter(|c| !c.is_control() && *c != ':').collect();
    let base = base.trim().trim_start_matches('.').to_string();
    if base.is_empty() { "download".into() } else { base }
}

/// Download from the local backend to a file the user picks in the native save panel.
/// WKWebView cancels `<a download>` and attachment navigations, so the app routes every
/// download through here. The destination only ever comes from the save panel, so the web
/// view can't direct a write anywhere else. Returns the saved path, or None if cancelled.
#[tauri::command]
async fn save_download(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Backend>,
    path: String,
    filename: String,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    if !valid_api_path(&path) {
        return Err("Not a downloadable backend path.".into());
    }
    let url = format!("http://127.0.0.1:{}{}", state.port, path);
    let auth = format!("Bearer {}", state.token);
    let name = clean_file_name(&filename);
    tauri::async_runtime::spawn_blocking(move || -> Result<Option<String>, String> {
        let Some(dest) = window.dialog().file().set_parent(&window).set_file_name(&name).blocking_save_file() else {
            return Ok(None);
        };
        let dest = dest.into_path().map_err(|e| e.to_string())?;
        let resp = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(5))
            .build()
            .get(&url)
            .set("Authorization", &auth)
            .call()
            .map_err(|e| match e {
                ureq::Error::Status(404, _) => "The backend doesn't serve that file.".to_string(),
                ureq::Error::Status(code, _) => format!("The backend answered {code}."),
                other => format!("Couldn't reach the backend: {other}"),
            })?;
        // Write next to the destination, then rename, so a failed download never leaves a
        // truncated file in place of one the user chose to overwrite.
        let part = dest.with_file_name(format!(
            ".{}.download",
            dest.file_name().and_then(|n| n.to_str()).unwrap_or("file")
        ));
        let write = (|| -> std::io::Result<()> {
            let mut out = fs::File::create(&part)?;
            std::io::copy(&mut resp.into_reader(), &mut out)?;
            out.sync_all()?;
            fs::rename(&part, &dest)
        })();
        if let Err(e) = write {
            let _ = fs::remove_file(&part);
            return Err(format!("Couldn't save {}: {e}", dest.display()));
        }
        Ok(Some(dest.display().to_string()))
    })
    .await
    .map_err(|e| e.to_string())?
}

/// File types `open_file` hands to their default app: documents and media. Nothing that runs
/// code when opened (apps, scripts, installers, shortcuts, .terminal/.command files, source
/// files whose default app may be an interpreter): those are revealed in Finder instead.
const OPENABLE: &[&str] = &[
    "html", "htm", "pdf", "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "avif", "bmp", "tif", "tiff",
    "svg", "mp3", "wav", "m4a", "aac", "flac", "ogg", "oga", "opus", "aiff", "aif", "mp4", "m4v", "mov",
    "webm", "ogv", "txt", "md", "markdown", "csv", "tsv", "json", "log", "rtf", "doc", "docx", "xls",
    "xlsx", "ppt", "pptx", "pages", "numbers", "key", "odt", "ods", "odp", "epub", "srt", "vtt",
];

fn openable(path: &std::path::Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| OPENABLE.contains(&e.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

/// Open a local file the backend serves (artifact, attachment, session file) in its default app,
/// e.g. HTML in the default browser as file:// — never a backend URL, which would carry the
/// session token. The backend decides which paths are allowed (/api/file/resolve: the data dir
/// and session folders); only document and media types are opened. Errors with "not_openable"
/// for other types, so the UI can reveal the file in Finder instead.
#[tauri::command]
async fn open_file(app: AppHandle, state: tauri::State<'_, Backend>, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let url = format!("http://127.0.0.1:{}/api/file/resolve", state.port);
    let auth = format!("Bearer {}", state.token);
    let real = tauri::async_runtime::spawn_blocking(move || -> Result<PathBuf, String> {
        let resp = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(5))
            .timeout(Duration::from_secs(10))
            .build()
            .get(&url)
            .query("path", &path)
            .set("Authorization", &auth)
            .call()
            .map_err(|e| match e {
                ureq::Error::Status(404, _) => "GameDevWorkstation doesn't serve that file.".to_string(),
                ureq::Error::Status(code, _) => format!("The backend answered {code}."),
                other => format!("Couldn't reach the backend: {other}"),
            })?;
        let body: serde_json::Value =
            serde_json::from_str(&resp.into_string().map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        body.get("path")
            .and_then(|p| p.as_str())
            .map(PathBuf::from)
            .ok_or_else(|| "The backend sent no path.".to_string())
    })
    .await
    .map_err(|e| e.to_string())??;
    if !real.is_absolute() || !real.is_file() || !openable(&real) {
        return Err("not_openable".into());
    }
    app.opener().open_path(real.to_string_lossy(), None::<&str>).map_err(|e| e.to_string())
}

fn build_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let new_session = MenuItem::with_id(app, "new_session", "New Session", true, Some("CmdOrCtrl+N"))?;
    let settings = MenuItem::with_id(app, "settings", "Settings…", true, Some("CmdOrCtrl+,"))?;
    let search = MenuItem::with_id(app, "search", "Search…", true, Some("CmdOrCtrl+K"))?;
    let terminal = MenuItem::with_id(app, "toggle_terminal", "Toggle Terminal", true, Some("CmdOrCtrl+J"))?;
    let help = MenuItem::with_id(app, "help", "Keyboard Shortcuts", true, Some("CmdOrCtrl+/"))?;
    // Session menu: ids are handled by the UI (App.tsx useShortcuts). Move to Trash has no
    // accelerator here because ⌘⌫ must keep deleting text in fields; the UI handles it outside them.
    let prev_session = MenuItem::with_id(app, "prev_session", "Previous Session", true, Some("CmdOrCtrl+Shift+["))?;
    let next_session = MenuItem::with_id(app, "next_session", "Next Session", true, Some("CmdOrCtrl+Shift+]"))?;
    let rename_session = MenuItem::with_id(app, "rename_session", "Rename Session", true, Some("F2"))?;
    let pin_session = MenuItem::with_id(app, "pin_session", "Pin or Unpin Session", true, Some("CmdOrCtrl+Shift+P"))?;
    let trash_session = MenuItem::with_id(app, "trash_session", "Move Session to Trash", true, None::<&str>)?;
    let app_menu = Submenu::with_items(
        app,
        "GameDevWorkstation",
        true,
        &[
            &PredefinedMenuItem::about(app, Some("About GameDevWorkstation"), Some(AboutMetadata::default()))?,
            &PredefinedMenuItem::separator(app)?,
            &new_session,
            &settings,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::services(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, None)?,
            &PredefinedMenuItem::hide_others(app, None)?,
            &PredefinedMenuItem::show_all(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::quit(app, None)?,
        ],
    )?;
    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        "View",
        true,
        &[&search, &terminal, &PredefinedMenuItem::separator(app)?, &PredefinedMenuItem::fullscreen(app, None)?],
    )?;
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    let session_menu = Submenu::with_items(
        app,
        "Session",
        true,
        &[
            &prev_session,
            &next_session,
            &PredefinedMenuItem::separator(app)?,
            &rename_session,
            &pin_session,
            &trash_session,
        ],
    )?;
    let help_menu = Submenu::with_items(app, "Help", true, &[&help])?;
    Menu::with_items(app, &[&app_menu, &edit, &view, &session_menu, &window, &help_menu])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .invoke_handler(tauri::generate_handler![backend_info, restart_backend, power_status, save_download, open_file])
        .setup(|app| {
            let handle = app.handle().clone();
            let port = free_port();
            let token = random_token();
            rotate_log(&logs_dir().join(STDOUT_LOG), LOG_KEEP, LOG_CAP_BYTES);
            app.manage(BackendHealth::default());
            let child = spawn_backend(&handle, port, &token).map_err(|e| format!("couldn't start the backend: {e}"))?;
            let dir = data_dir();
            let _ = fs::create_dir_all(&dir);
            let runtime_file = dir.join("runtime.json");
            // For `make app-test` and debugging: where the running backend lives. Owner-only.
            let info = serde_json::json!({ "port": port, "token": token, "backend_pid": child.id(), "app_pid": std::process::id() });
            let _ = write_private(&runtime_file, info.to_string().as_bytes());
            app.manage(Backend { port, token, child: Mutex::new(Some(child)), runtime_file });
            app.set_menu(build_menu(&handle)?)?;
            // If the backend dies while the app runs, tell the UI (it shows the "engine stopped" screen).
            let watcher = handle.clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_secs(1));
                if let Some(exit) = poll_exit(&watcher) {
                    let _ = watcher.emit("backend-exited", exit);
                }
            });
            Ok(())
        })
        .on_menu_event(|app, event| {
            let _ = app.emit("menu", event.id().as_ref().to_string());
        })
        .build(tauri::generate_context!())
        .expect("error while building GameDevWorkstation");

    app.run(|handle, event| match event {
        RunEvent::ExitRequested { .. } | RunEvent::Exit => stop_backend(handle),
        RunEvent::WindowEvent { event: tauri::WindowEvent::Destroyed, .. } => {
            // Last window gone (closed or crashed): quit, which stops the backend.
            if handle.webview_windows().is_empty() {
                stop_backend(handle);
                handle.exit(0);
            }
        }
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn api_paths() {
        assert!(valid_api_path("/api/file?path=%2Ftmp%2Fa.txt&download=1"));
        assert!(valid_api_path("/api/usage/export.csv?since=1"));
        assert!(!valid_api_path("http://evil.example/api/x"));
        assert!(!valid_api_path("//evil.example/api/x"));
        assert!(!valid_api_path("/api//evil"));
        assert!(!valid_api_path("/health"));
        assert!(!valid_api_path("/api/x\r\nHost: evil"));
        assert!(!valid_api_path("/api/x y"));
    }

    #[test]
    fn openable_types() {
        use std::path::Path;
        assert!(openable(Path::new("/a/report.html")));
        assert!(openable(Path::new("/a/Slides.PDF")));
        assert!(openable(Path::new("/a/clip.mov")));
        for p in ["/a/run.command", "/a/x.app", "/a/x.terminal", "/a/s.sh", "/a/s.py", "/a/i.pkg", "/a/w.webloc",
                  "/a/noext", "/a/s.scpt", "/a/j.jar", "/a/report.html.command"] {
            assert!(!openable(Path::new(p)), "{p}");
        }
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("ws-test-{name}-{}-{}", std::process::id(), random_token()));
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn log_rotation_keeps_three_and_caps_size() {
        let d = scratch_dir("rotate");
        let log = d.join(STDOUT_LOG);
        let n = |i: usize| d.join(format!("{STDOUT_LOG}.{i}"));
        for run in 1..=5 {
            fs::write(&log, format!("run {run}\n")).unwrap();
            rotate_log(&log, 3, 1024);
        }
        assert!(!log.exists());
        assert_eq!(fs::read_to_string(n(1)).unwrap(), "run 5\n");
        assert_eq!(fs::read_to_string(n(3)).unwrap(), "run 3\n");
        assert!(!n(4).exists());
        // Too big: only the end is kept.
        fs::write(&log, format!("{}END", "x".repeat(5000))).unwrap();
        rotate_log(&log, 3, 100);
        let kept = fs::read_to_string(n(1)).unwrap();
        assert_eq!(kept.len(), 100);
        assert!(kept.ends_with("END"));
        // Empty or missing: nothing moves.
        fs::write(&log, "").unwrap();
        rotate_log(&log, 3, 100);
        assert!(log.exists() && fs::read_to_string(n(1)).unwrap().ends_with("END"));
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn tail_of_log() {
        let d = scratch_dir("tail");
        let log = d.join("l.log");
        let body: String = (1..=100).map(|i| format!("line {i}\n")).collect();
        fs::write(&log, body).unwrap();
        assert_eq!(tail_lines(&log, 3), "line 98\nline 99\nline 100");
        assert_eq!(tail_lines(&d.join("missing.log"), 3), "");
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn file_names() {
        assert_eq!(clean_file_name("report.csv"), "report.csv");
        assert_eq!(clean_file_name("../../etc/passwd"), "passwd");
        assert_eq!(clean_file_name("a/b\\c.md"), "c.md");
        assert_eq!(clean_file_name(".zshrc"), "zshrc");
        assert_eq!(clean_file_name("  "), "download");
        assert_eq!(clean_file_name("My: talk.md"), "My talk.md");
    }
}
