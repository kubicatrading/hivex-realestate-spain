import hmac
import hashlib
import os
import time
import jwt
from typing import Optional, Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

# Security Configuration
SECRET_KEY = getattr(settings, "SECRET_KEY", "hivex-secret-key-309182390182309182039")
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 86400 # 24 hours

security = HTTPBearer(auto_error=False)

# Static Authorized Configuration
SALT = "hivex_salt_2026_spain"

AUTHORIZED_LOGINS = {
    "jsaavedra": "semeviene@hotmail.es",
    "admin": "admin@hivex.es",
    "semeviene@hotmail.es": "semeviene@hotmail.es",
    "admin@hivex.es": "admin@hivex.es"
}

# Supported passwords
VALID_PASSWORDS = [
    "9gc#7vaQQ_U58FZ",
    "hivex1234#"
]

# Allow custom credentials via environment variables if provided
if os.environ.get("AUTH_USERNAME"):
    u = os.environ.get("AUTH_USERNAME").strip().lower()
    AUTHORIZED_LOGINS[u] = os.environ.get("AUTH_EMAIL", f"{u}@hivex.es")

if os.environ.get("AUTH_PASSWORD"):
    VALID_PASSWORDS.append(os.environ.get("AUTH_PASSWORD").strip())

def hash_password(password: str, salt: str = SALT) -> str:
    """Hashes a password using PBKDF2 HMAC SHA256."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()

VALID_HASHES = [hash_password(p, SALT) for p in VALID_PASSWORDS]

def verify_credentials(login_input: str, password_input: str) -> Optional[Dict[str, str]]:
    """
    Validates credentials matching either username OR email (case-insensitive)
    against authorized passwords.
    """
    clean_login = (login_input or "").strip().lower()
    clean_pass = (password_input or "").strip()
    
    if not clean_login or not clean_pass:
        return None
    
    if clean_login not in AUTHORIZED_LOGINS:
        return None

    computed_hash = hash_password(clean_pass, SALT)
    is_valid_pass = any(hmac.compare_digest(computed_hash, vh) for vh in VALID_HASHES)
    
    if is_valid_pass:
        canonical_user = clean_login.split("@")[0] if "@" in clean_login else clean_login
        if canonical_user in ("semeviene", "jsaavedra"):
            canonical_user = "jsaavedra"
            email = "semeviene@hotmail.es"
        else:
            canonical_user = clean_login
            email = AUTHORIZED_LOGINS.get(clean_login, f"{clean_login}@hivex.es")
            
        return {
            "username": canonical_user,
            "email": email
        }
    
    return None

def create_access_token(data: dict) -> str:
    """Generates a signed JWT access token."""
    to_encode = data.copy()
    expire = time.time() + TOKEN_EXPIRE_SECONDS
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, str]:
    """FastAPI Dependency to verify JWT Bearer token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Por favor, inicie sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de acceso no válido",
            )
        return {
            "username": username,
            "email": payload.get("email", f"{username}@hivex.es")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ha caducado. Vuelva a iniciar sesión.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar el token de autenticación.",
        )

def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, str]]:
    """FastAPI Dependency for optional authentication."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            return None
        return {
            "username": username,
            "email": payload.get("email", f"{username}@hivex.es")
        }
    except Exception:
        return None

