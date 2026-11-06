CREDENCIALES PARA EL EMPAQUETADO (opcional pero recomendado)
============================================================

Si quieres que la app instalada tenga el LOGIN de Google y el CHAT (Gemini)
listos sin que el usuario configure nada, coloca AQUÍ estos archivos ANTES de
correr `npm run tauri:build` (desde frontend/):

  1) client_secret.json   -> credenciales OAuth de Google (login + export Drive)
  2) .env                 -> con la línea:  GEMINI_API_KEY=tu_clave_aqui

Qué pasa al empaquetar:
  - FaceSyncEngine.spec los bundlea dentro del engine.
  - En el primer arranque, bridge._seed_private_config los copia a:
        %LOCALAPPDATA%\FaceSync\config\
    que es donde el motor los busca (oauth_service / chat_service).

Si NO los pones:
  - La CLASIFICACIÓN funciona igual (no depende de estas claves).
  - El login Google y el chat quedan deshabilitados hasta que el usuario
    coloque client_secret.json y .env en %LOCALAPPDATA%\FaceSync\config\.

NOTA DE SEGURIDAD: client_secret.json y .env son secretos. NO los subas a git.
Este README sí se versiona; los secretos NO.
