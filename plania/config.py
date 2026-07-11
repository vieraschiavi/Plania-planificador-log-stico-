"""
Plania · Configuración persistente (API keys)
============================================
Guarda las API keys una sola vez y las reutiliza en cada arranque, sin tener
que reingresarlas.

Backend de guardado, en orden de preferencia (se detecta solo, sin que el
usuario tenga que elegir nada):

  1. **Keyring del sistema operativo** (Windows Credential Manager / macOS
     Keychain / Secret Service en Linux de escritorio) — lo más seguro,
     y es el caso normal para el instalador de Windows.
  2. **Archivo cifrado** (`config.enc`, Fernet/AES) si no hay keyring
     disponible (servidor headless, contenedor, CI) — la clave de cifrado
     vive en un archivo separado con permisos 600.
  3. **Texto plano** (`config.json`, permisos 600) solo si ninguna librería
     de cifrado está instalada — último recurso, nunca el default.

Todo vive fuera del repo, en `$PLANIA_CONFIG_DIR` (por defecto ~/.plania).
Precedencia: una variable de entorno real (inyectada en producción) tiene
prioridad sobre lo guardado. `aplicar()` carga las keys guardadas al entorno
para que el Copiloto (Claude/Anthropic) y las integraciones funcionen automáticamente.
"""
import json
import os

CONFIG_DIR = os.environ.get("PLANIA_CONFIG_DIR", os.path.expanduser("~/.plania"))
CONFIG_FILE_PLANO = os.path.join(CONFIG_DIR, "config.json")
CONFIG_FILE_CIFRADO = os.path.join(CONFIG_DIR, "config.enc")
CLAVE_CIFRADO_FILE = os.path.join(CONFIG_DIR, ".config.key")
KEYRING_SERVICE = "plania-ia"
KEYRING_USER = "plania-config"

CLAVES = {
    "ANTHROPIC_API_KEY": "Anthropic · Copiloto IA (chat sobre tus datos reales)",
    "ERP_DB_URL": "ERP · URL de conexión a la base de datos (SQLAlchemy: postgresql://, mysql+pymysql://, mssql+pyodbc://, oracle://, sqlite:///…)",
    "ERP_API_URL": "ERP · URL del endpoint/webhook para sincronizar pedidos y ofertas",
    "ERP_API_KEY": "ERP · API key (Bearer) del endpoint",
    "MP_ACCESS_TOKEN": "MercadoPago · Access Token (cobros de planes y checkout)",
    "SMTP_HOST": "Email · servidor SMTP corporativo (ej. smtp.tuempresa.com)",
    "SMTP_PORT": "Email · puerto SMTP (ej. 587)",
    "SMTP_USER": "Email · usuario/cuenta SMTP",
    "SMTP_PASSWORD": "Email · contraseña / app password SMTP",
    "SMTP_FROM": "Email · dirección remitente (ej. ventas@tuempresa.com)",
}


# ---------------------------------------------------------------------------
# Backend de guardado: keyring > archivo cifrado > texto plano
# ---------------------------------------------------------------------------
def _keyring_disponible():
    try:
        import keyring
        from keyring.errors import KeyringError
        try:
            keyring.get_keyring()
            # Backend "fail" existe pero no sirve: probamos un roundtrip real.
            keyring.set_password(KEYRING_SERVICE, "_plania_probe", "ok")
            ok = keyring.get_password(KEYRING_SERVICE, "_plania_probe") == "ok"
            keyring.delete_password(KEYRING_SERVICE, "_plania_probe")
            return keyring if ok else None
        except KeyringError:
            return None
    except Exception:
        return None


def _cifrado_disponible():
    try:
        from cryptography.fernet import Fernet  # noqa: F401
        return True
    except Exception:
        return False


def _clave_cifrado():
    """Clave Fernet persistida en un archivo separado (600), generada una vez."""
    from cryptography.fernet import Fernet
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CLAVE_CIFRADO_FILE):
        with open(CLAVE_CIFRADO_FILE, "rb") as f:
            return f.read()
    clave = Fernet.generate_key()
    with open(CLAVE_CIFRADO_FILE, "wb") as f:
        f.write(clave)
    try:
        os.chmod(CLAVE_CIFRADO_FILE, 0o600)
    except OSError:
        pass
    return clave


def backend_activo() -> str:
    """Cuál backend se está usando ahora mismo: 'keyring' | 'cifrado' | 'plano'."""
    if _keyring_disponible():
        return "keyring"
    if _cifrado_disponible():
        return "cifrado"
    return "plano"


def _cargar_keyring(kr) -> dict:
    raw = kr.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _guardar_keyring(kr, cfg: dict):
    kr.set_password(KEYRING_SERVICE, KEYRING_USER, json.dumps(cfg))


def _cargar_cifrado() -> dict:
    if not os.path.exists(CONFIG_FILE_CIFRADO):
        return {}
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_clave_cifrado())
        with open(CONFIG_FILE_CIFRADO, "rb") as fh:
            return json.loads(f.decrypt(fh.read()))
    except Exception:
        return {}


def _guardar_cifrado(cfg: dict):
    from cryptography.fernet import Fernet
    f = Fernet(_clave_cifrado())
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE_CIFRADO, "wb") as fh:
        fh.write(f.encrypt(json.dumps(cfg).encode("utf-8")))
    try:
        os.chmod(CONFIG_FILE_CIFRADO, 0o600)
    except OSError:
        pass


def _cargar_plano() -> dict:
    if os.path.exists(CONFIG_FILE_PLANO):
        try:
            with open(CONFIG_FILE_PLANO, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _guardar_plano(cfg: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE_PLANO, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(CONFIG_FILE_PLANO, 0o600)
    except OSError:
        pass


def cargar() -> dict:
    kr = _keyring_disponible()
    if kr:
        return _cargar_keyring(kr)
    if _cifrado_disponible():
        return _cargar_cifrado()
    return _cargar_plano()


def guardar(nuevos: dict) -> dict:
    """Guarda solo las keys con valor; no pisa las existentes con vacíos."""
    cfg = cargar()
    for k, v in nuevos.items():
        if k in CLAVES and v and v.strip():
            cfg[k] = v.strip()
            os.environ[k] = v.strip()

    kr = _keyring_disponible()
    if kr:
        _guardar_keyring(kr, cfg)
    elif _cifrado_disponible():
        _guardar_cifrado(cfg)
    else:
        _guardar_plano(cfg)
    return cfg


def leer_extra(clave: str, default=None):
    """Lee un valor persistido que no es una API key de `CLAVES` (ej. hashes de
    autenticación) — mismo backend seguro (keyring/cifrado/plano), sin tocar
    el entorno ni aparecer en la pestaña Configuración."""
    return cargar().get(clave, default)


def guardar_extra(clave: str, valor) -> None:
    """Persiste un valor que no es una API key de `CLAVES` (ej. hashes de
    autenticación), en el mismo backend seguro que `guardar()`."""
    cfg = cargar()
    cfg[clave] = valor
    kr = _keyring_disponible()
    if kr:
        _guardar_keyring(kr, cfg)
    elif _cifrado_disponible():
        _guardar_cifrado(cfg)
    else:
        _guardar_plano(cfg)


def limpiar():
    """Borra la configuración guardada (en cualquier backend) y las keys del entorno."""
    kr = _keyring_disponible()
    if kr:
        try:
            kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass
    for path in (CONFIG_FILE_CIFRADO, CONFIG_FILE_PLANO):
        if os.path.exists(path):
            os.remove(path)
    for k in CLAVES:
        os.environ.pop(k, None)


def aplicar():
    """Carga las keys guardadas al entorno (sin pisar variables ya presentes)."""
    for k, v in cargar().items():
        if v and not os.environ.get(k):
            os.environ[k] = v


def estado() -> dict:
    """Devuelve qué keys están activas (por entorno o archivo)."""
    aplicar()
    return {k: bool(os.environ.get(k)) for k in CLAVES}


def enmascarar(valor: str) -> str:
    if not valor:
        return ""
    return f"{valor[:3]}…{valor[-4:]}" if len(valor) > 8 else "•••"
