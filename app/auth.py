"""User class (class diagram): login(), logout(), with lockout after repeated failures."""
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from .db import now

MAX_FAILED = 5
LOCK_MINUTES = 5


def create_user(conn, username, password, role="admin"):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    conn.execute("INSERT INTO user(username,password,role) VALUES(?,?,?)",
                 (username, generate_password_hash(password), role))
    conn.commit()


def login(conn, username, password):
    """Return the user row on success, or (None, reason) on failure."""
    row = conn.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone()
    if row is None:
        return None, "Invalid username or password"
    if row["locked_until"]:
        until = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if until > datetime.now(timezone.utc):
            return None, "Account temporarily locked. Try again later."
    if check_password_hash(row["password"], password):
        conn.execute("UPDATE user SET failed_logins=0, locked_until=NULL WHERE user_id=?", (row["user_id"],))
        conn.commit()
        return row, None
    fails = row["failed_logins"] + 1
    locked = None
    if fails >= MAX_FAILED:
        locked = (datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        fails = 0
    conn.execute("UPDATE user SET failed_logins=?, locked_until=? WHERE user_id=?",
                 (fails, locked, row["user_id"]))
    conn.commit()
    return None, "Invalid username or password"
