"""Authentication & User Management for Evidence Browser.
Provider pattern for OAuth-ready design. Currently implements local auth."""

import os
import uuid
import secrets
import sqlite3
import bcrypt
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from pathlib import Path

DB_PATH = Path(__file__).parent / "auth.db"

# Roles & Permissions
PERMISSIONS = {
    'admin': ['*'],
    'analyst': ['view_devices', 'view_records', 'search', 'view_discoveries',
                'view_chats', 'view_media', 'view_legal', 'view_mindmap',
                'use_ai_chat', 'export'],
    'viewer': ['view_devices', 'view_records', 'search', 'view_discoveries',
               'view_chats', 'view_media', 'view_legal', 'view_mindmap'],
    'legal': ['view_legal', 'view_discoveries', 'search'],
}

VALID_ROLES = list(PERMISSIONS.keys())

# Rate limiting config
MAX_FAILED_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
LOCKOUT_DURATION = 30 * 60   # 30 minutes
SESSION_EXPIRY_HOURS = 24


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create auth tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            email TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            auth_provider TEXT DEFAULT 'local',
            auth_provider_id TEXT,
            password_hash TEXT,
            created_at TEXT,
            last_login TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT,
            expires_at TEXT,
            ip_address TEXT,
            user_agent TEXT
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            ip_address TEXT,
            success INTEGER,
            timestamp TEXT
        );
    """)
    conn.commit()
    conn.close()


class AuthProvider:
    """Base auth provider interface."""
    def authenticate(self, credentials: dict) -> Optional[dict]:
        raise NotImplementedError
    def create_credentials(self, user_id: str, password: str) -> str:
        raise NotImplementedError


class LocalAuthProvider(AuthProvider):
    """Username + bcrypt password authentication."""

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except Exception:
            return False


class AuthManager:
    """Central auth manager with provider pattern."""

    def __init__(self):
        self.providers: Dict[str, AuthProvider] = {
            'local': LocalAuthProvider(),
        }
        init_db()

    def _provider(self, name: str = 'local') -> AuthProvider:
        return self.providers[name]

    # --- User Management ---

    def create_user(self, username: str, password: str, role: str = 'viewer',
                    display_name: str = None, email: str = None) -> dict:
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {role}")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(username) < 2:
            raise ValueError("Username must be at least 2 characters")

        provider = self._provider('local')
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        password_hash = provider.hash_password(password)

        conn = _get_db()
        try:
            conn.execute(
                "INSERT INTO users (id, username, display_name, email, role, auth_provider, password_hash, created_at, is_active) VALUES (?,?,?,?,?,?,?,?,1)",
                (user_id, username, display_name or username, email, role, 'local', password_hash, now)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            raise ValueError(f"Username '{username}' already exists")
        conn.close()
        logging.getLogger('auth').info(f"USER_CREATED username={username} role={role}")
        return {"id": user_id, "username": username, "role": role, "display_name": display_name or username}

    def get_user(self, user_id: str) -> Optional[dict]:
        conn = _get_db()
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._user_dict(row)

    def get_user_by_username(self, username: str) -> Optional[dict]:
        conn = _get_db()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if not row:
            return None
        return self._user_dict(row, include_hash=True)

    def list_users(self) -> List[dict]:
        conn = _get_db()
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        conn.close()
        return [self._user_dict(r) for r in rows]

    def update_user(self, user_id: str, **kwargs) -> Optional[dict]:
        allowed = {'display_name', 'email', 'role', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if 'role' in updates and updates['role'] not in VALID_ROLES:
            raise ValueError(f"Invalid role: {updates['role']}")
        if not updates:
            return self.get_user(user_id)

        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [user_id]
        conn = _get_db()
        conn.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
        conn.commit()
        conn.close()
        user = self.get_user(user_id)
        if user:
            logging.getLogger('auth').info(f"USER_UPDATED target={user.get('username')} changes={list(updates.keys())}")
        return user

    def deactivate_user(self, user_id: str) -> bool:
        conn = _get_db()
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (user_id,))
        # Revoke all sessions
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        return True

    def reset_password(self, user_id: str, new_password: str) -> bool:
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        provider = self._provider('local')
        password_hash = provider.hash_password(new_password)
        conn = _get_db()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        user = self.get_user(user_id)
        logging.getLogger('auth').info(f"PASSWORD_RESET target={user.get('username') if user else user_id}")
        return True

    # --- Authentication ---

    def login(self, username: str, password: str, ip: str = None, user_agent: str = None) -> Optional[dict]:
        """Authenticate and create session. Returns {token, user} or None."""
        auth_log = logging.getLogger('auth')

        # Check rate limit
        if self._is_rate_limited(ip):
            auth_log.warning(f"RATE_LIMITED ip={ip} username={username}")
            self._log_attempt(username, ip, False)
            return None

        user = self.get_user_by_username(username)
        if not user or not user.get('is_active'):
            reason = "unknown_user" if not user else "inactive_account"
            auth_log.warning(f"LOGIN_FAILED username={username} ip={ip} reason={reason}")
            self._log_attempt(username, ip, False)
            return None

        provider = self._provider(user.get('auth_provider', 'local'))
        if not isinstance(provider, LocalAuthProvider):
            auth_log.warning(f"LOGIN_FAILED username={username} ip={ip} reason=unsupported_provider")
            self._log_attempt(username, ip, False)
            return None

        if not provider.verify_password(password, user.get('_password_hash', '')):
            auth_log.warning(f"LOGIN_FAILED username={username} ip={ip} reason=bad_password")
            self._log_attempt(username, ip, False)
            return None

        # Success
        auth_log.info(f"LOGIN_SUCCESS username={username} ip={ip}")
        self._log_attempt(username, ip, True)
        token = self._create_session(user['id'], ip, user_agent)

        # Update last_login
        conn = _get_db()
        conn.execute("UPDATE users SET last_login=? WHERE id=?",
                      (datetime.now(timezone.utc).isoformat(), user['id']))
        conn.commit()
        conn.close()

        safe_user = {k: v for k, v in user.items() if not k.startswith('_')}
        return {"token": token, "user": safe_user}

    def validate_session(self, token: str) -> Optional[dict]:
        """Validate session token, return user or None."""
        if not token:
            return None
        conn = _get_db()
        row = conn.execute(
            "SELECT s.*, u.* FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=? AND u.is_active=1",
            (token,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        # Check expiry
        expires = row['expires_at']
        if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
            self._revoke_session(token)
            return None
        return self._user_dict(row)

    def logout(self, token: str) -> bool:
        # Log who's logging out
        user = self.validate_session(token)
        if user:
            logging.getLogger('auth').info(f"LOGOUT username={user.get('username')}")
        self._revoke_session(token)
        return True

    # --- Rate Limiting ---

    def _is_rate_limited(self, ip: str) -> bool:
        if not ip:
            return False
        conn = _get_db()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=RATE_LIMIT_WINDOW)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM login_attempts WHERE ip_address=? AND success=0 AND timestamp>?",
            (ip, cutoff)
        ).fetchone()
        conn.close()
        return (row['cnt'] or 0) >= MAX_FAILED_ATTEMPTS

    def _log_attempt(self, username: str, ip: str, success: bool):
        conn = _get_db()
        conn.execute(
            "INSERT INTO login_attempts (username, ip_address, success, timestamp) VALUES (?,?,?,?)",
            (username, ip, int(success), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()

    # --- Sessions ---

    def _create_session(self, user_id: str, ip: str = None, user_agent: str = None) -> str:
        token = secrets.token_hex(64)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=SESSION_EXPIRY_HOURS)
        conn = _get_db()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at, ip_address, user_agent) VALUES (?,?,?,?,?,?)",
            (token, user_id, now.isoformat(), expires.isoformat(), ip, user_agent)
        )
        conn.commit()
        conn.close()
        return token

    def _revoke_session(self, token: str):
        conn = _get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()

    # --- Login History ---

    def get_login_history(self, limit: int = 100) -> List[dict]:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM login_attempts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Helpers ---

    def _user_dict(self, row, include_hash: bool = False) -> dict:
        d = {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "email": row["email"],
            "role": row["role"],
            "auth_provider": row["auth_provider"],
            "created_at": row["created_at"],
            "last_login": row["last_login"],
            "is_active": bool(row["is_active"]),
        }
        if include_hash:
            d["_password_hash"] = row["password_hash"]
        return d

    def has_permission(self, user: dict, permission: str) -> bool:
        role = user.get('role', 'viewer')
        perms = PERMISSIONS.get(role, [])
        return '*' in perms or permission in perms

    # --- Initial Setup ---

    def ensure_admin_exists(self) -> Optional[str]:
        """Create default admin if no users exist. Returns password if created."""
        conn = _get_db()
        count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']
        conn.close()
        if count > 0:
            return None

        password = os.environ.get('EVIDENCE_ADMIN_PASSWORD') or secrets.token_urlsafe(16)
        self.create_user(
            username='admin',
            password=password,
            role='admin',
            display_name='Administrator',
        )
        return password


# Singleton
auth_manager = AuthManager()
