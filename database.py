import sqlite3
import json
from datetime import datetime

DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Store bot config and admins
    c.execute('''CREATE TABLE IF NOT EXISTS config
                 (key TEXT PRIMARY KEY, value TEXT)''')
    # Store user last welcome time
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, username TEXT, last_welcome TEXT)''')
    # Store daily stats
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (date TEXT PRIMARY KEY, total_msgs INTEGER, active_users TEXT, joined_users TEXT)''')
    conn.commit()
    conn.close()

def set_config(key, value):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()

def get_config(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return default

def update_user_welcome(user_id, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT OR REPLACE INTO users (user_id, username, last_welcome) VALUES (?, ?, ?)", (user_id, username, now))
    conn.commit()
    conn.close()

def get_user_last_welcome(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT last_welcome FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0])
    return None

# Initialize on import
init_db()