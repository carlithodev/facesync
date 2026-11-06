// FaceSyncV2 — shell Tauri. Arranca el sidecar Python (engine/bridge.py) como
// proceso hijo y hace de relé: stdout(JSON) -> eventos "sidecar://msg",
// stderr(logs) -> "sidecar://log". El front envía peticiones con el comando
// `sidecar_send` (escribe una línea JSON en el stdin del sidecar).
//
// Usa std::process::Command directo (no plugin-shell): el sidecar es fijo y
// controlado por la app, así que no exponemos ejecución arbitraria a JS.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use tauri::{Emitter, Manager, State};
use tauri_plugin_opener::OpenerExt;

struct Sidecar {
    stdin: Mutex<Option<ChildStdin>>,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn sidecar_send(line: String, state: State<Sidecar>) -> Result<(), String> {
    if line.len() > 1024 * 1024 {
        return Err("peticion demasiado grande".into());
    }
    if line.contains('\n') || line.contains('\r') {
        return Err("la peticion debe ocupar una sola linea".into());
    }
    let message: serde_json::Value = serde_json::from_str(&line)
        .map_err(|_| "peticion JSON invalida".to_string())?;
    if message.get("id").and_then(|v| v.as_str()).is_none()
        || message.get("cmd").and_then(|v| v.as_str()).is_none()
        || !message.get("args").map(|v| v.is_object()).unwrap_or(true)
    {
        return Err("contrato de peticion invalido".into());
    }
    let mut guard = state.stdin.lock().map_err(|e| e.to_string())?;
    match guard.as_mut() {
        Some(stdin) => {
            stdin.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
            stdin.write_all(b"\n").map_err(|e| e.to_string())?;
            stdin.flush().map_err(|e| e.to_string())?;
            Ok(())
        }
        None => Err("sidecar no iniciado".into()),
    }
}

#[tauri::command]
fn read_file_b64(path: String) -> Result<String, String> {
    // Lee un archivo local y lo devuelve en base64 (para el visor de imágenes,
    // sin tener que configurar el asset-scope de Tauri).
    use base64::Engine;
    const MAX_IMAGE_BYTES: u64 = 100 * 1024 * 1024;
    const IMAGE_EXTENSIONS: &[&str] = &["jpg", "jpeg", "png", "gif", "bmp", "webp"];
    let image_path = Path::new(&path);
    let extension = image_path.extension().and_then(|v| v.to_str()).unwrap_or("").to_ascii_lowercase();
    if !IMAGE_EXTENSIONS.contains(&extension.as_str()) {
        return Err("solo se permite leer formatos de imagen soportados".into());
    }
    let metadata = std::fs::metadata(image_path).map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.len() > MAX_IMAGE_BYTES {
        return Err("imagen invalida o demasiado grande".into());
    }
    let bytes = std::fs::read(image_path).map_err(|e| e.to_string())?;
    Ok(base64::engine::general_purpose::STANDARD.encode(bytes))
}

const EXCEL_TEMPLATE: &[u8] = include_bytes!("../resources/templates/Plantilla_FaceSync.xlsx");

#[derive(serde::Serialize)]
struct ExcelFileInfo {
    path: String,
    name: String,
    size: u64,
    modified_ms: u64,
}

fn is_inside_workspace(path: &Path, roots: &[String]) -> bool {
    roots.iter().any(|root| {
        PathBuf::from(root)
            .canonicalize()
            .map(|root_path| path.starts_with(root_path))
            .unwrap_or(false)
    })
}

fn validate_excel_name(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    let stem = if trimmed.to_ascii_lowercase().ends_with(".xlsx") {
        &trimmed[..trimmed.len() - 5]
    } else {
        trimmed
    }
    .trim();
    if stem.is_empty() {
        return Err("escribe un nombre para el Excel".into());
    }
    if stem == "." || stem == ".." || stem.ends_with('.') || stem.ends_with(' ')
        || stem.chars().any(|c| c.is_control() || "<>:\"/\\|?*".contains(c))
    {
        return Err("el nombre del Excel contiene caracteres no permitidos".into());
    }
    let reserved = stem
        .split('.')
        .next()
        .unwrap_or(stem)
        .to_ascii_uppercase();
    if matches!(reserved.as_str(), "CON" | "PRN" | "AUX" | "NUL" | "COM1" | "COM2" | "COM3" | "COM4" | "COM5" | "COM6" | "COM7" | "COM8" | "COM9" | "LPT1" | "LPT2" | "LPT3" | "LPT4" | "LPT5" | "LPT6" | "LPT7" | "LPT8" | "LPT9") {
        return Err("ese nombre está reservado por Windows".into());
    }
    Ok(format!("{stem}.xlsx"))
}

fn excel_file_info(path: &Path) -> Result<ExcelFileInfo, String> {
    let metadata = std::fs::metadata(path).map_err(|e| e.to_string())?;
    if !metadata.is_file() {
        return Err("la ruta no corresponde a un archivo".into());
    }
    let modified_ms = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0);
    Ok(ExcelFileInfo {
        path: path.to_string_lossy().replace('\\', "/"),
        name: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
        size: metadata.len(),
        modified_ms,
    })
}

#[tauri::command]
fn create_excel_template(name: String, directory: String, roots: Vec<String>) -> Result<ExcelFileInfo, String> {
    let directory_path = PathBuf::from(directory)
        .canonicalize()
        .map_err(|_| "la carpeta seleccionada ya no existe".to_string())?;
    if !directory_path.is_dir() || !is_inside_workspace(&directory_path, &roots) {
        return Err("selecciona una carpeta que pertenezca al workspace".into());
    }
    let filename = validate_excel_name(&name)?;
    let destination = directory_path.join(filename);
    if destination.exists() {
        return Err("ya existe un archivo con ese nombre en la carpeta seleccionada".into());
    }

    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&destination)
        .map_err(|e| format!("no se pudo crear el Excel: {e}"))?;
    if let Err(error) = file.write_all(EXCEL_TEMPLATE).and_then(|_| file.sync_all()) {
        drop(file);
        let _ = std::fs::remove_file(&destination);
        return Err(format!("no se pudo guardar la plantilla: {error}"));
    }
    drop(file);
    excel_file_info(&destination)
}

#[tauri::command]
fn open_excel_file(app: tauri::AppHandle, path: String, roots: Vec<String>) -> Result<(), String> {
    let file_path = PathBuf::from(path)
        .canonicalize()
        .map_err(|_| "el Excel ya no existe".to_string())?;
    let extension = file_path.extension().and_then(|value| value.to_str()).unwrap_or("");
    if !file_path.is_file() || !extension.eq_ignore_ascii_case("xlsx") || !is_inside_workspace(&file_path, &roots) {
        return Err("el archivo no es un Excel válido del workspace".into());
    }
    app.opener()
        .open_path(file_path.to_string_lossy().to_string(), None::<String>)
        .map_err(|error| format!("Windows no pudo abrir el Excel: {error}"))
}

#[tauri::command]
fn open_drive_folder(app: tauri::AppHandle, folder_id: Option<String>) -> Result<(), String> {
    let url = if let Some(folder_id) = folder_id.filter(|value| !value.is_empty()) {
        let valid = folder_id.len() <= 256
            && folder_id.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_');
        if !valid {
            return Err("el identificador de la carpeta de Drive no es válido".into());
        }
        format!("https://drive.google.com/drive/folders/{folder_id}")
    } else {
        "https://drive.google.com/drive/my-drive".to_string()
    };
    app.opener()
        .open_url(url, None::<String>)
        .map_err(|error| format!("no se pudo abrir Google Drive: {error}"))
}

#[tauri::command]
fn excel_file_state(path: String, roots: Vec<String>) -> Result<ExcelFileInfo, String> {
    let file_path = PathBuf::from(path)
        .canonicalize()
        .map_err(|_| "el Excel ya no existe".to_string())?;
    let extension = file_path.extension().and_then(|value| value.to_str()).unwrap_or("");
    if !extension.eq_ignore_ascii_case("xlsx") || !is_inside_workspace(&file_path, &roots) {
        return Err("el archivo no es un Excel válido del workspace".into());
    }
    excel_file_info(&file_path)
}

#[derive(serde::Serialize)]
struct AccountInfo {
    email_safe: String,
    email: String,
    name: String,
    picture: Option<String>,
}

#[tauri::command]
fn list_local_accounts() -> Vec<AccountInfo> {
    // Lee engine/usuarios/<email>/ (token.json + config.json + perfil.png) en
    // RUST -> instantáneo, sin depender del warm del sidecar Python. Así el
    // login muestra las cuentas de inmediato (no "Arrancando motor…").
    let mut out: Vec<AccountInfo> = vec![];
    let mut seen = HashSet::new();
    for dir in account_dirs() {
      if let Ok(entries) = std::fs::read_dir(&dir) {
        for e in entries.flatten() {
            let p = e.path();
            if !p.is_dir() || !p.join("token.json").exists() {
                continue;
            }
            let email_safe = e.file_name().to_string_lossy().to_string();
            if email_safe == "." || email_safe == ".."
                || !email_safe.chars().all(|c| c.is_ascii_alphanumeric() || "@._+-".contains(c))
                || !seen.insert(email_safe.clone())
            {
                continue;
            }
            let mut name = String::new();
            let mut email = email_safe.clone();
            if let Ok(txt) = std::fs::read_to_string(p.join("config.json")) {
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) {
                    name = v.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string();
                    email = v.get("email").and_then(|x| x.as_str()).unwrap_or(&email_safe).to_string();
                }
            }
            if name.trim().is_empty() {
                name = email_safe.split('@').next().unwrap_or(&email_safe).to_string();
            }
            let perfil = p.join("perfil.png");
            let picture = if perfil.exists() {
                Some(perfil.to_string_lossy().replace('\\', "/"))
            } else {
                None
            };
            out.push(AccountInfo { email_safe, email, name, picture });
        }
      }
    }
    out
}

fn account_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        dirs.push(PathBuf::from(local).join("FaceSync").join("usuarios"));
    }
    dirs.push(PathBuf::from(engine_dir()).join("usuarios"));
    dirs
}

fn engine_dir() -> String {
    // Override en runtime con FACESYNC_ENGINE_DIR; por defecto, relativo a este
    // crate (dev): .../frontend/src-tauri -> ../../engine.
    std::env::var("FACESYNC_ENGINE_DIR").unwrap_or_else(|_| {
        format!("{}/../../engine", env!("CARGO_MANIFEST_DIR"))
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar {
            stdin: Mutex::new(None),
            child: Mutex::new(None),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let dev_dir = PathBuf::from(engine_dir());
            let dev_python = dev_dir.join("env_ia").join("Scripts").join("python.exe");
            let dev_bridge = dev_dir.join("bridge.py");
            let use_dev_engine = cfg!(debug_assertions) && dev_python.is_file() && dev_bridge.is_file();

            // Busca el sidecar empaquetado en TODAS las rutas donde Tauri/NSIS
            // pudo dejarlo: la ubicación exacta de resource_dir varía por versión
            // e instalador (a veces incluye el prefijo `resources/`, a veces no).
            // Antes solo se probaba `resource_dir/engine` -> en una PC sin el
            // python de dev el sidecar no se encontraba y no arrancaba.
            let resource_dir = app.path().resource_dir().ok();
            let exe_parent = std::env::current_exe()
                .ok()
                .and_then(|p| p.parent().map(|d| d.to_path_buf()));
            let mut exe_candidates: Vec<PathBuf> = Vec::new();
            for base in [resource_dir.clone(), exe_parent.clone()].into_iter().flatten() {
                exe_candidates.push(base.join("engine").join("FaceSyncEngine.exe"));
                exe_candidates.push(base.join("resources").join("engine").join("FaceSyncEngine.exe"));
            }
            let packaged_exe = exe_candidates.iter().find(|p| p.is_file()).cloned();
            let packaged_dir = packaged_exe
                .as_ref()
                .and_then(|p| p.parent().map(|d| d.to_path_buf()));

            let (mut command, working_dir, launch_description) = if use_dev_engine {
                let mut cmd = Command::new(&dev_python);
                cmd.arg(&dev_bridge);
                (
                    cmd,
                    dev_dir.clone(),
                    format!("{} {}", dev_python.display(), dev_bridge.display()),
                )
            } else if let (Some(executable), Some(cwd)) = (packaged_exe.clone(), packaged_dir.clone()) {
                (Command::new(&executable), cwd, executable.display().to_string())
            } else {
                // Último recurso (solo útil en dev): python + bridge del árbol.
                eprintln!(
                    "sidecar empaquetado NO encontrado. Rutas probadas: {:?}",
                    exe_candidates
                );
                let mut cmd = Command::new(&dev_python);
                cmd.arg(&dev_bridge);
                (
                    cmd,
                    dev_dir.clone(),
                    format!("{} {}", dev_python.display(), dev_bridge.display()),
                )
            };

            // Windows: no mostrar la ventana de consola del sidecar. CREATE_NO_WINDOW
            // oculta la consola pero conserva los pipes stdin/stdout (protocolo JSON).
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                const CREATE_NO_WINDOW: u32 = 0x0800_0000;
                command.creation_flags(CREATE_NO_WINDOW);
            }

            let spawned = command
                // DeepFace/RetinaFace requieren Keras 2. Debe llegar al sidecar
                // antes de que su arranque importe TensorFlow.
                .env("TF_USE_LEGACY_KERAS", "1")
                .current_dir(&working_dir)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn();
            let mut child = match spawned {
                Ok(c) => c,
                Err(e) => {
                    // No abortamos la app: avisamos al front y seguimos (UI viva).
                    let msg = format!("no se pudo arrancar el sidecar ({launch_description}): {e}");
                    eprintln!("{msg}");
                    let _ = handle.emit("sidecar://error", msg);
                    return Ok(());
                }
            };

            let stdout = child.stdout.take().expect("stdout");
            let stderr = child.stderr.take().expect("stderr");
            let stdin = child.stdin.take().expect("stdin");

            let state: State<Sidecar> = app.state();
            *state.stdin.lock().unwrap() = Some(stdin);
            *state.child.lock().unwrap() = Some(child);

            // stdout (protocolo JSON) -> evento por línea
            let h1 = handle.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    let _ = h1.emit("sidecar://msg", line);
                }
                let _ = h1.emit("sidecar://closed", "stdout");
            });

            // stderr (diagnóstico) -> evento por línea
            let h2 = handle.clone();
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().map_while(Result::ok) {
                    let _ = h2.emit("sidecar://log", line);
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // Al cerrar, matar el sidecar para no dejar pythons huérfanos en dev.
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<Sidecar>();
                let mut guard = state.child.lock().unwrap();
                if let Some(child) = guard.as_mut() {
                    let _ = child.kill();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            sidecar_send,
            read_file_b64,
            list_local_accounts,
            create_excel_template,
            open_excel_file,
            open_drive_folder,
            excel_file_state,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
