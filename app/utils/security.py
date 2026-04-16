from datetime import datetime, timedelta, timezone
from pathlib import Path

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Cargar llaves RSA ────────────────────────────────────
_private_key: str | None = None
_public_key: str | None = None

_priv_path = Path(settings.JWT_PRIVATE_KEY_PATH)
_pub_path = Path(settings.JWT_PUBLIC_KEY_PATH)

if _priv_path.exists():
    _private_key = _priv_path.read_text()
if _pub_path.exists():
    _public_key = _pub_path.read_text()

if not _private_key or not _public_key:
    raise RuntimeError(
        f"RSA keys not found at {_priv_path} / {_pub_path}. "
        "Generate with: openssl genrsa -out private_key.pem 2048 && "
        "openssl rsa -in private_key.pem -pubout -out public_key_local.pem"
    )


# ── Password hashing (bcrypt) ───────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


# ── JWT RS256 ────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, _private_key, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, _private_key, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decodifica un JWT. Intenta RS256 local primero, luego RS256 VPS, luego HS256 legacy."""
    # 1. RS256 con llave pública local
    try:
        return jwt.decode(token, _public_key, algorithms=["RS256"])
    except Exception:
        pass

    # 2. RS256 con llave pública del VPS (si existe)
    vps_pub_path = Path("app/assets/keys/public_key.pem")
    if vps_pub_path.exists():
        try:
            vps_key = vps_pub_path.read_text()
            return jwt.decode(token, vps_key, algorithms=["RS256"])
        except Exception:
            pass

    # 3. HS256 legacy (tokens antiguos durante migración)
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
