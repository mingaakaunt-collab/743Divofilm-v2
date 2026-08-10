import sqlite3

DB_NAME = "movies.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            name TEXT,
            lang TEXT,
            quality TEXT,
            message_id INTEGER,
            channel_id INTEGER
        )
    ''')
    cursor.execute('DROP TABLE IF EXISTS channels')
    cursor.execute('''
        CREATE TABLE channels (
            chat_id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            style TEXT,
            emoji_id TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_movies (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    ''')
    conn.commit()
    # Ensure join_requests table exists for subscription tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS join_requests (
            user_id INTEGER,
            chat_id TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    # Table for share links (multiple links per movie allowed)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS share_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            secret TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Table for referral tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_user_id INTEGER NOT NULL,
            secret TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.close()

def add_channel(chat_id, name, url, style, emoji_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO channels (chat_id, name, url, style, emoji_id) VALUES (?, ?, ?, ?, ?)', (str(chat_id), name, url, style, emoji_id))
    conn.commit()
    conn.close()

def remove_channel(chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE chat_id = ?', (str(chat_id),))
    conn.commit()
    conn.close()

def get_channels():
    """Return list of all mandatory channels."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, name, url, style, emoji_id FROM channels')
    rows = cursor.fetchall()
    conn.close()
    return [
        {"chat_id": row[0], "name": row[1], "url": row[2], "style": row[3], "emoji_id": row[4]}
        for row in rows
    ]


def add_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_new_user_count(days):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE created_at >= datetime("now", "-" || ? || " days")', (days,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_user_count():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_user_ids():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_movie_count():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM movies')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_movies():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT code, name, lang, quality FROM movies ORDER BY rowid DESC')
    rows = cursor.fetchall()
    conn.close()
    return [{"code": r[0], "name": r[1], "lang": r[2], "quality": r[3]} for r in rows]

def delete_movie(code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM movies WHERE code = ?', (code,))
    conn.commit()
    conn.close()

def add_join_request(user_id, chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO join_requests (user_id, chat_id) VALUES (?, ?)', (user_id, str(chat_id)))
    conn.commit()
    conn.close()

def has_join_request(user_id, chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM join_requests WHERE user_id = ? AND chat_id = ?', (user_id, str(chat_id)))
    result = cursor.fetchone()
    conn.close()
    return bool(result)

def add_movie(code, file_id, name, lang, quality, message_id=None, channel_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO movies (code, file_id, name, lang, quality, message_id, channel_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (code, file_id, name, lang, quality, message_id, channel_id))
    conn.commit()
    conn.close()

def get_movie(code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, name, lang, quality FROM movies WHERE code = ?', (code,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "file_id": result[0],
            "name": result[1],
            "lang": result[2],
            "quality": result[3]
        }
    return None

def get_movie_by_secret(secret):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.file_id, m.name, m.lang, m.quality, m.code
        FROM movies m
        JOIN share_links s ON m.code = s.code
        WHERE s.secret = ?
    ''', (secret,))
    result = cursor.fetchone()
    # Consume the secret (one‑time use)
    cursor.execute('DELETE FROM share_links WHERE secret = ?', (secret,))
    conn.commit()
    conn.close()
    if result:
        return {"file_id": result[0], "name": result[1], "lang": result[2], "quality": result[3], "code": result[4]}
    return None

def create_share_secret(code, referrer_id=None):
    """Create a new unique secret for a given movie code and store it.
    Optionally record the referrer (user who generated the share link).
    Returns the generated secret string.
    """
    import uuid, sqlite3
    secret = uuid.uuid4().hex
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Store in share_links for one‑time use
    cursor.execute('INSERT INTO share_links (code, secret) VALUES (?, ?)', (code, secret))
    # Record referrer if provided
    if referrer_id is not None:
        cursor.execute('INSERT INTO referrals (referrer_id, referred_user_id, secret) VALUES (?, NULL, ?)', (referrer_id, secret))
    conn.commit()
    conn.close()
    return secret

def get_referrer_by_secret(secret):
    """Return the referrer_id associated with a share secret, or None if not found."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id FROM referrals WHERE secret = ?', (secret,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def record_referral(secret, referred_user_id):
    """Update the referral row with the ID of the user who used the link."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE referrals SET referred_user_id = ? WHERE secret = ?', (referred_user_id, secret))
    conn.commit()
    conn.close()

def save_movie(user_id, code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO saved_movies (user_id, code) VALUES (?, ?)', (user_id, code))
    conn.commit()
    conn.close()

def remove_saved_movie(user_id, code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM saved_movies WHERE user_id = ? AND code = ?', (user_id, code))
    conn.commit()
    conn.close()

def get_saved_movies(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.code, m.name, m.lang, m.quality, m.file_id
        FROM saved_movies s
        JOIN movies m ON s.code = m.code
        WHERE s.user_id = ?
    ''', (user_id,))
    result = cursor.fetchall()
    conn.close()
    return [{"code": r[0], "name": r[1], "lang": r[2], "quality": r[3], "file_id": r[4]} for r in result]
