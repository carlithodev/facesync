<p align="center">
  <img src="frontend/src-tauri/icons/icon.png" alt="FaceSync" width="150">
</p>

# FaceSyncV2

Aplicación de escritorio para organizar y clasificar fotografías mediante
referencias de Excel/CSV. La interfaz actual usa React + Tauri y se comunica con
el motor Python mediante JSON Lines por `stdin/stdout`.

## Desarrollo

Requisitos: Node compatible con Vite 8, Rust estable y Python 3.11 de 64 bits.

1. Crea `engine/env_ia` con `python -m venv engine/env_ia`.
2. Instala `python -m pip install -r engine/requirements.txt`.
3. Copia `engine/.env.example` como `engine/.env` y configura las claves.
4. Guarda el OAuth de Google en `%LOCALAPPDATA%/FaceSync/config/client_secret.json`
   o define `FACESYNC_GOOGLE_CLIENT_SECRET`.
5. En `frontend`, ejecuta `npm ci` y después `npm run tauri dev`.

Los tokens, perfiles, historial, caché facial y configuración se almacenan en
`%LOCALAPPDATA%/FaceSync`; no deben versionarse ni distribuirse con la app.

## Seguridad

- Todas las operaciones del explorador quedan limitadas a las raíces activas.
- Quitar una raíz del workspace no borra su contenido.
- Los embeddings son datos biométricos locales: usa la opción de limpieza antes
  de entregar o reutilizar un equipo.
- Nunca publiques `.env`, `client_secret.json` ni carpetas `usuarios`.

## Verificación

- Frontend: `npm run build`
- Rust: `cargo check --manifest-path frontend/src-tauri/Cargo.toml`
- Python: `python -m unittest discover -s engine/tests -v`

