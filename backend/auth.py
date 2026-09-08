"""
Authentication module: self-declared role-based accounts.

Design notes (see AGENTS.md / project_status_checklist.md, Stage 2):
- Role is self-declared at signup, NOT identity-verified. This is
  role-based PERSONALIZATION enforced at the API layer, not a security
  boundary against someone falsely claiming a professional identity.
  Say this explicitly in the paper if this feature is described there.
- Backed by a dedicated SQLite file (backend/data/users.db), kept fully
  separate from mapping.db (which is a generated artifact, rebuilt from
  ipc_bns_mapping.csv on every startup if the CSV is newer). users.db
  must NEVER be dropped/regenerated — it holds real user data. Only
  CREATE TABLE IF NOT EXISTS is used here, never a rebuild-from-source
  step like mapping.db has.
- No refresh-token flow, no email verification, no password reset —
  deliberately out of scope for this project. Token expiry is long
  (24h) to avoid needing a refresh flow at all.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

load_dotenv()

# --- Config ------------------------------------------------------------------

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY not set. Add a long random string to backend/.env, e.g.\n"
        '  JWT_SECRET_KEY=<output of `python -c "import secrets; print(secrets.token_hex(32))"`>'
    )

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

VALID_ROLES = ("lawyer", "judge", "student", "public")

DB_PATH = Path(__file__).parent / "data" / "users.db"

# tokenUrl is just for OpenAPI docs' "Authorize" button - doesn't affect behavior
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])


# --- DB setup ------------------------------------------------------------------

def init_users_db() -> None:
    """Create the users table if it doesn't exist. Call this once at server
    startup (see main.py integration notes). Safe to call every startup —
    CREATE TABLE IF NOT EXISTS never touches existing rows."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('lawyer','judge','student','public')),
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --- Schemas ------------------------------------------------------------------

class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class CurrentUser(BaseModel):
    user_id: int
    username: str
    role: str


# --- Internal helpers ------------------------------------------------------------------

def hash_password(password: str) -> str:
    """bcrypt has a hard 72-byte input limit; truncate defensively (signup
    already caps password length at 128 chars via the schema, but this
    guards against any bytes-vs-chars edge case with non-ASCII input)."""
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))


def _create_access_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# --- Routes ------------------------------------------------------------------

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest):
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {VALID_ROLES}")

    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (req.username,)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Username already taken")

        password_hash = hash_password(req.password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (req.username, password_hash, req.role, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        user_id = cursor.lastrowid
    finally:
        conn.close()

    token = _create_access_token(
        {"sub": req.username, "user_id": user_id, "role": req.role},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token, username=req.username, role=req.role)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, password_hash, role FROM users WHERE username = ?",
            (req.username,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    token = _create_access_token(
        {"sub": req.username, "user_id": row["id"], "role": row["role"]},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token, username=req.username, role=row["role"])


# --- Dependencies for role-gating other routers ------------------------------

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> CurrentUser:
    credentials_exception = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        user_id = payload.get("user_id")
        role = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return CurrentUser(user_id=user_id, username=username, role=role)


def require_role(*allowed_roles: str):
    """Dependency factory for gating other routers by role, e.g.:

        from auth import require_role
        @router.post("/upload")
        def upload(..., user = Depends(require_role("lawyer", "judge"))):
            ...

    Do NOT wire this into existing routes (documents.py, qa.py, search.py)
    yet - get signup/login verified standalone first, per the project's
    usual verify-before-proceeding convention.
    """
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This feature requires role: {', '.join(allowed_roles)}",
            )
        return user
    return _check