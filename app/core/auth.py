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
TOKEN_EXPIRE_SECONDS = 86400 * 7 # 24 hours x 7 days

security = HTTPBearer(auto_error=False)

# Static Authorized User
AUTHORIZED_USER = {
    "username": "jsaavedra",
    "email": "semeviene@hotmail.es",
    # PBKDF2 salt and hash for 'hivex1234#'
    "salt": "hivex_salt_2026_spain",
    "password_hash": "26d6e75a6c4df1d36d4f6c5bb5d2b78a9c228805f2b861280fa7f1396b2ed4c6"
}

def hash_password(password: str, salt: str = AUTHORIZED_USER["salt"]) -> str:
    """Hashes a password using PBKDF2 HMAC SHA256."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()

# Initialize authorized hash
AUTHORIZED_USER["password_hash"] = hash_password("hivex1234#", AUTHORIZED_USER["salt"])

def verify_credentials(login_input: str, password_input: str) -> Optional[Dict[str, str]]:
    """
    Validates credentials matching either username OR email (case-insensitive).
    """
    clean_login = login_input.strip().lower()
    
    is_valid_user = (
        clean_login == AUTHORIZED_USER["username"].lower() or 
        clean_login == AUTHORIZED_USER["email"].lower()
    )
    
    if not is_valid_user:
        return None

    computed_hash = hash_password(password_input, AUTHORIZED_USER["salt"])
    if hmac.compare_digest(computed_hash, AUTHORIZED_USER["password_hash"]):
        return {
            "username": AUTHORIZED_USER["username"],
            "email": AUTHORIZED_USER["email"]
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
        username: str = payload.get("sub")
        if username != AUTHORIZED_USER["username"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de acceso no válido",
            )
        return {"username": AUTHORIZED_USER["username"], "email": AUTHORIZED_USER["email"]}
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
