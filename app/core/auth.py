import hmac
import hashlib
import os
import secrets
import time
import jwt
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.core.config import settings
from app.db.models import User

# Security Configuration
SECRET_KEY = getattr(settings, "SECRET_KEY", "hivex-secret-key-309182390182309182039")
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 86400 # 24 hours

security = HTTPBearer(auto_error=False)

DEFAULT_SALT = "hivex_salt_2026_spain"
DEFAULT_USER = "jsaavedra"
DEFAULT_EMAIL = "semeviene@hotmail.es"
DEFAULT_PASS = "hivex1234#"

def hash_password(password: str, salt: str = DEFAULT_SALT) -> str:
    """Hashes a password using PBKDF2 HMAC SHA256."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()

def seed_default_user(db: Session) -> User:
    """Ensures the primary admin user exists in the database."""
    try:
        user = db.query(User).filter(
            or_(
                func.lower(User.username) == DEFAULT_USER.lower(),
                func.lower(User.email) == DEFAULT_EMAIL.lower()
            )
        ).first()

        if not user:
            user_salt = secrets.token_hex(16)
            hashed_pwd = hash_password(DEFAULT_PASS, user_salt)
            user = User(
                username=DEFAULT_USER,
                email=DEFAULT_EMAIL,
                hashed_password=hashed_pwd,
                salt=user_salt,
                is_active=True,
                is_admin=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        return None

def verify_credentials(db: Optional[Session], login_input: str, password_input: str) -> Optional[Dict[str, Any]]:
    """
    Validates credentials matching either username OR email (case-insensitive)
    against the User table in the database.
    """
    clean_login = (login_input or "").strip().lower()
    clean_pass = (password_input or "").strip()
    
    if not clean_login or not clean_pass:
        return None

    # 1. Check in database if db session is provided
    if db is not None:
        try:
            user = db.query(User).filter(
                or_(
                    func.lower(User.username) == clean_login,
                    func.lower(User.email) == clean_login
                )
            ).first()

            if not user:
                # If table is empty, auto-seed and retry
                total_users = db.query(User).count()
                if total_users == 0:
                    user = seed_default_user(db)
                    if user and (clean_login in (user.username.lower(), user.email.lower())):
                        pass
                    else:
                        user = None

            if user and user.is_active:
                computed_hash = hash_password(clean_pass, user.salt or DEFAULT_SALT)
                if hmac.compare_digest(computed_hash, user.hashed_password):
                    return {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "is_admin": user.is_admin
                    }
        except Exception as e:
            # Fallback if DB connectivity issue during login
            pass

    # 2. In-memory fallback for primary user
    if clean_login in (DEFAULT_USER.lower(), DEFAULT_EMAIL.lower()):
        if clean_pass == DEFAULT_PASS:
            return {
                "id": 1,
                "username": DEFAULT_USER,
                "email": DEFAULT_EMAIL,
                "is_admin": True
            }

    return None

def create_access_token(data: dict) -> str:
    """Generates a signed JWT access token."""
    to_encode = data.copy()
    expire = time.time() + TOKEN_EXPIRE_SECONDS
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
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
            "email": payload.get("email", f"{username}@hivex.es"),
            "is_admin": payload.get("is_admin", True)
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ha caducado. Vuelva a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar el token de autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """FastAPI Dependency for optional authentication."""
    if not credentials:
        return None
    try:
        return get_current_user(credentials)
    except Exception:
        return None


