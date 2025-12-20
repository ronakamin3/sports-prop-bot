import sqlite3
import time

DB_NAME = "bot.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent (
            id TEXT PRIMARY KEY,
            ts INTEGER
        )
    """)
    conn.commit()
    conn.close()

def was_sent_recently(key, minutes):
    cutoff = int(time.time()) - minutes * 60
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT ts FROM sent WHERE id = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] > cutoff

def mark_sent(key):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO sent (id, ts) VALUES (?, ?)",
        (key, int(time.time()))
    )
    conn.commit()
    conn.close()
