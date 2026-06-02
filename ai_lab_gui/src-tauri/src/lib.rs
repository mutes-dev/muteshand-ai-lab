use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// Module-level handle to the backend subprocess.
/// Must be module-level so both setup and the exit handler can reach it.
static BACKEND_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

/// Expected app instance ID generated at Tauri startup.
/// Used by frontend to verify backend identity via /identity.
static APP_INSTANCE_ID: Mutex<Option<String>> = Mutex::new(None);

/// Startup error set if backend identity verification fails.
/// Frontend reads this via Tauri command to show a specific error message.
static STARTUP_ERROR: Mutex<Option<String>> = Mutex::new(None);

fn generate_app_instance_id() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis();
    format!("ailab-{}-{}", std::process::id(), now)
}

fn start_backend(app_instance_id: &str) -> Child {
    Command::new("C:\\Python313\\python.exe")
        .current_dir("E:\\MutesHand")
        .env("AI_LAB_APP_INSTANCE_ID", app_instance_id)
        .env("AI_LAB_LAUNCH_MODE", "tauri")
        .arg("-m")
        .arg("uvicorn")
        .arg("ai_lab_gui.backend.api:app")
        .arg("--port")
        .arg("8000")
        .spawn()
        .expect("Failed to start backend — ensure Python and uvicorn are installed")
}

/// ISSUE-063: Verify the backend on port 8000 belongs to this app instance.
/// Retries for up to 8 seconds to allow uvicorn to bind.
/// Returns Ok if identity matches; Err with descriptive message otherwise.
fn verify_backend_identity(app_instance_id: &str) -> Result<(), String> {
    let url = "http://localhost:8000/identity";
    let start = Instant::now();
    let timeout = Duration::from_secs(8);

    while start.elapsed() < timeout {
        match ureq::get(url).timeout(Duration::from_secs(2)).call() {
            Ok(response) => {
                let body = response.into_string()
                    .map_err(|e| format!("Failed to read identity body: {}", e))?;
                let identity: serde_json::Value = serde_json::from_str(&body)
                    .map_err(|e| format!("Failed to parse identity JSON: {}", e))?;

                let returned_id = identity.get("app_instance_id").and_then(|v| v.as_str());
                match returned_id {
                    Some(id) if id == app_instance_id => return Ok(()),
                    Some(id) => {
                        return Err(format!(
                            "Backend identity mismatch: expected '{}', got '{}'. Another AI Lab backend may be running on port 8000.",
                            app_instance_id, id
                        ));
                    }
                    None => {
                        return Err(
                            "Backend on port 8000 missing app_instance_id — external or incompatible process."
                                .to_string(),
                        );
                    }
                }
            }
            Err(ureq::Error::Status(code, _)) => {
                if code == 404 {
                    return Err(
                        "Port 8000 occupied by a process without /identity endpoint — external or unrelated backend."
                            .to_string(),
                    );
                }
                // Other HTTP errors may be transient; retry
            }
            Err(ureq::Error::Transport(transport)) => {
                let msg = transport.message().unwrap_or("unknown");
                if msg.contains("Connection refused")
                    || msg.contains("No connection could be made")
                    || msg.contains("os error 10061")
                {
                    // Backend hasn't bound yet, normal during startup
                } else {
                    return Err(format!("Unexpected transport error contacting /identity: {}", msg));
                }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    Err("Backend did not respond with matching identity within timeout. Port 8000 may be occupied by an incompatible process, or the backend failed to start.".to_string())
}

#[tauri::command]
fn get_app_instance_id() -> Option<String> {
    let id = APP_INSTANCE_ID.lock().unwrap().clone();
    println!("[ISSUE-063] get_app_instance_id called, returning: {:?}", id);
    id
}

#[tauri::command]
fn get_startup_error() -> Option<String> {
    STARTUP_ERROR.lock().unwrap().clone()
}

pub fn run() {
    let app_instance_id = generate_app_instance_id();

    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_app_instance_id, get_startup_error])
        .setup(move |_app| {
            let child = start_backend(&app_instance_id);
            *BACKEND_PROCESS.lock().unwrap() = Some(child);
            *APP_INSTANCE_ID.lock().unwrap() = Some(app_instance_id.clone());

            // ISSUE-063: Verify backend identity before trusting it
            match verify_backend_identity(&app_instance_id) {
                Ok(()) => {}
                Err(err) => {
                    eprintln!("[ISSUE-063] Startup identity check failed: {}", err);
                    *STARTUP_ERROR.lock().unwrap() = Some(err);
                }
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(mut child) = BACKEND_PROCESS.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
