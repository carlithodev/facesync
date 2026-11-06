"""
oauth_service.py — Login Google OAuth (headless), extraído de facesyncApp.login.

Sin CustomTkinter: el flujo abre el navegador del sistema (run_local_server),
igual que el original. Guarda token/config/avatar bajo engine/usuarios/<email>/.

Funciones:
  list_accounts()        -> [{email, name, picture}]
  login()                -> {email, name, picture}  (abre navegador; bloquea)
  login_saved(email)     -> {email, name, picture}  (refresca token guardado)
  delete_account(email)  -> {deleted: email}
"""

import os
import json
import re
import shutil
import urllib.request
import urllib.parse
from pathlib import Path

from facesyncApp import BASE_DIR
from core.app_paths import ensure_app_data_root

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
    "openid",
]

# Página HTML que ve el usuario en el navegador al terminar el login con Google
# (google-auth-oauthlib la sirve como cuerpo HTML directo).
_SUCCESS_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FaceSync · Sesión iniciada</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    background:#070710;color:#fff;overflow:hidden;position:relative}
  .orb{position:fixed;border-radius:50%;filter:blur(130px);pointer-events:none}
  .orb.a{width:520px;height:520px;background:rgba(217,70,239,.18);top:-160px;right:-140px}
  .orb.b{width:520px;height:520px;background:rgba(79,70,229,.22);bottom:-180px;left:-130px}
  .card{position:relative;z-index:1;width:min(440px,92vw);padding:44px 36px;text-align:center;
    border-radius:28px;border:1px solid rgba(255,255,255,.10);
    background:rgba(255,255,255,.03);backdrop-filter:blur(18px);
    box-shadow:0 30px 80px rgba(0,0,0,.5)}
  .logo{font-size:34px;font-weight:800;letter-spacing:-1px;margin-bottom:26px}
  .logo b{color:#fff}.logo span{background:linear-gradient(90deg,#6366f1,#a855f7,#d946ef);
    -webkit-background-clip:text;background-clip:text;color:transparent}
  .check{width:84px;height:84px;border-radius:50%;margin:0 auto 22px;
    display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#22c55e,#10b981);
    box-shadow:0 0 0 8px rgba(16,185,129,.12);animation:pop .5s cubic-bezier(.18,1.4,.4,1) both}
  .check svg{width:42px;height:42px;stroke:#fff;stroke-width:3.2;fill:none;
    stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:48;
    stroke-dashoffset:48;animation:draw .5s .25s ease forwards}
  h1{font-size:23px;font-weight:700;margin-bottom:10px}
  p{font-size:15px;line-height:1.5;color:#9aa3b2}
  .hint{margin-top:24px;font-size:13px;color:#6b7280}
  @keyframes pop{from{transform:scale(.5);opacity:0}to{transform:scale(1);opacity:1}}
  @keyframes draw{to{stroke-dashoffset:0}}
</style></head>
<body>
  <div class="orb a"></div><div class="orb b"></div>
  <div class="card">
    <div class="logo"><b>Face</b><span>Sync</span></div>
    <div class="check"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></div>
    <h1>¡Sesión iniciada!</h1>
    <p>Tu cuenta de Google quedó conectada a FaceSync.</p>
    <p class="hint">Ya puedes cerrar esta pestaña y volver a la aplicación.</p>
  </div>
</body></html>"""


_ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+\-]{0,253}\Z")
_MAX_AVATAR_BYTES = 8 * 1024 * 1024


def _account_id(value) -> str:
    """Valida el identificador usado como nombre de carpeta de una cuenta."""
    text = str(value or "").strip()
    if text in {"", ".", ".."} or not _ACCOUNT_ID_RE.fullmatch(text):
        raise ValueError("identificador de cuenta invalido")
    return text


def _legacy_users_dir() -> Path:
    return Path(BASE_DIR) / "usuarios"


def _users_dir() -> str:
    """Datos privados fuera del arbol de codigo (LocalAppData/FaceSync)."""
    d = ensure_app_data_root() / "usuarios"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _account_locations(email_safe: str) -> list[Path]:
    key = _account_id(email_safe)
    return [Path(_users_dir()) / key, _legacy_users_dir() / key]


def _existing_account_dir(email_safe: str) -> Path:
    locations = _account_locations(email_safe)
    for location in locations:
        if (location / "token.json").is_file():
            return location
    return locations[0]


def token_path_for_account(email_safe: str) -> str:
    """Ruta del token vigente, compatible con cuentas legacy."""
    return str(_existing_account_dir(email_safe) / "token.json")


def client_secret_path() -> str:
    configured_secret = os.environ.get("FACESYNC_GOOGLE_CLIENT_SECRET", "").strip()
    private_secret = ensure_app_data_root() / "config" / "client_secret.json"
    legacy_secret = Path(BASE_DIR) / "client_secret.json"
    return next(
        (str(path) for path in (Path(configured_secret).expanduser() if configured_secret else None, private_secret, legacy_secret)
         if path is not None and path.is_file()),
        str(private_secret),
    )


def _write_private_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _account(email_safe):
    email_safe = _account_id(email_safe)
    user = str(_existing_account_dir(email_safe))
    name, email, picture = "", email_safe, None
    cfg = os.path.join(user, "config.json")
    if os.path.exists(cfg):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
            name = d.get("name", "")
            email = d.get("email", email_safe)
            picture = d.get("picture_url") or None
        except Exception:
            pass
    if not name:
        base = email_safe.split("@")[0]
        name = " ".join(p.capitalize() for p in base.replace(".", " ").replace("_", " ").split())
    pic_path = os.path.join(user, "perfil.png")
    return {"email_safe": email_safe, "email": email, "name": name,
            "picture": pic_path if os.path.exists(pic_path) else picture}


def list_accounts():
    out, seen = [], set()
    for users in (Path(_users_dir()), _legacy_users_dir()):
        if not users.is_dir():
            continue
        for entry in users.iterdir():
            try:
                key = _account_id(entry.name)
            except ValueError:
                continue
            if key in seen or not entry.is_dir() or not (entry / "token.json").is_file():
                continue
            seen.add(key)
            out.append(_account(key))
    return out


def delete_account(email_safe):
    key = _account_id(email_safe)
    for path in _account_locations(key):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
    return {"deleted": key}


def login_saved(email_safe):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    email_safe = _account_id(email_safe)
    ruta = token_path_for_account(email_safe)
    if not os.path.isfile(ruta):
        raise FileNotFoundError("no hay sesión guardada para esa cuenta")
    creds = Credentials.from_authorized_user_file(ruta)
    if creds and creds.valid:
        pass
    elif creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _write_private_text(Path(ruta), creds.to_json())
    else:
        raise PermissionError("la sesión expiró; inicia sesión de nuevo")
    return _account(email_safe)


def _download_avatar(picture_url, email_safe):
    """Descarga simple del avatar a perfil.png (sin recorte fancy; cosmético)."""
    if not picture_url:
        return None
    try:
        from PIL import Image
        import io
        parsed = urllib.parse.urlparse(str(picture_url))
        if parsed.scheme != "https":
            return None
        with urllib.request.urlopen(picture_url, timeout=10) as r:
            declared = int(r.headers.get("Content-Length") or 0)
            if declared > _MAX_AVATAR_BYTES:
                return None
            data = r.read(_MAX_AVATAR_BYTES + 1)
        if len(data) > _MAX_AVATAR_BYTES:
            return None
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        if img.width * img.height > 25_000_000:
            return None
        path = os.path.join(_users_dir(), _account_id(email_safe), "perfil.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path, "PNG")
        return path
    except Exception:
        return None


def login():
    """Flujo OAuth completo: abre navegador, obtiene credenciales, guarda perfil.
    BLOQUEA hasta que el usuario autoriza en el navegador."""
    import wsgiref.util
    from google_auth_oauthlib.flow import InstalledAppFlow
    import google_auth_oauthlib.flow as _gflow

    # El server interno sirve success_message como text/plain (se vería el HTML
    # como texto). Lo parcheamos a text/html para mostrar la página con estilo.
    def _html_call(self, environ, start_response):
        start_response("200 OK", [("Content-type", "text/html; charset=utf-8")])
        self.last_request_uri = wsgiref.util.request_uri(environ)
        return [self._success_message.encode("utf-8")]
    _gflow._RedirectWSGIApp.__call__ = _html_call

    ruta_json = client_secret_path()
    if not os.path.isfile(ruta_json):
        raise FileNotFoundError("falta client_secret.json en el engine")

    # Si el usuario no marca Drive, el token vuelve con menos scopes y oauthlib
    # lo trata como error fatal ("Scope has changed"). Relajamos esa validación.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow = InstalledAppFlow.from_client_secrets_file(ruta_json, SCOPES)
    # success_message se sirve como cuerpo HTML directo -> página con estilo.
    creds = flow.run_local_server(
        port=0, prompt="select_account",
        authorization_prompt_message="",
        success_message=_SUCCESS_HTML,
    )
    if not creds:
        raise RuntimeError("no se obtuvieron credenciales")

    name, picture_url, email = "", "", "unknown"
    try:
        req = urllib.request.Request("https://www.googleapis.com/oauth2/v2/userinfo")
        req.add_header("Authorization", f"Bearer {creds.token}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.loads(resp.read())
            email = info.get("email", "unknown")
            name = info.get("name", "")
            picture_url = info.get("picture", "")
    except Exception:
        pass

    email_safe = _account_id("".join(c for c in email if c.isalnum() or c in "@.+-_") )
    user = os.path.join(_users_dir(), email_safe)
    os.makedirs(user, exist_ok=True)
    _write_private_text(Path(user) / "token.json", creds.to_json())
    _write_private_text(
        Path(user) / "config.json",
        json.dumps({"name": name, "email": email, "picture_url": picture_url, "theme": "dark"},
                   ensure_ascii=False, indent=4),
    )
    _download_avatar(picture_url, email_safe)

    drive_ok = "drive.file" in " ".join(getattr(creds, "scopes", None) or [])
    acc = _account(email_safe)
    acc["drive_ok"] = drive_ok
    return acc
