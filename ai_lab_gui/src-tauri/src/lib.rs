use std::process::{Child, Command};
use std::sync::Mutex;

/// Module-level handle to the backend subprocess.
/// Must be module-level so both setup and the exit handler can reach it.
static BACKEND_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

fn start_backend() -> Child {
    Command::new("C:\\Python313\\python.exe")
        .current_dir("E:\\MutesHand")
        .arg("-m")
        .arg("uvicorn")
        .arg("ai_lab_gui.backend.api:app")
        .arg("--port")
        .arg("8000")
        .spawn()
        .expect("Failed to start backend — ensure Python and uvicorn are installed")
}

pub fn run() {
    let app = tauri::Builder::default()
        .setup(|_app| {
            let child = start_backend();
            *BACKEND_PROCESS.lock().unwrap() = Some(child);
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
