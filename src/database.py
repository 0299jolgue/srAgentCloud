import sqlite3
from config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                path       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS threads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title      TEXT NOT NULL DEFAULT 'New Thread',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id  INTEGER,
                project_id INTEGER,
                role       TEXT NOT NULL,
                type       TEXT NOT NULL DEFAULT 'text',
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (thread_id) REFERENCES threads(id)
            );
        """)
        # Add thread_id column for existing databases
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN thread_id INTEGER REFERENCES threads(id)")
        except Exception:
            pass

def save_message(thread_id: int, role: str, msg_type: str, content: str):
    with get_db() as conn:
        # Include project_id for backward compat with existing DBs that have NOT NULL on that column
        row = conn.execute("SELECT project_id FROM threads WHERE id=?", (thread_id,)).fetchone()
        project_id = row["project_id"] if row else None
        conn.execute(
            "INSERT INTO messages (thread_id, project_id, role, type, content) VALUES (?, ?, ?, ?, ?)",
            (thread_id, project_id, role, msg_type, content)
        )
