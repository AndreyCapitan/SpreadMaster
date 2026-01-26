import sqlite3
import hashlib
import os
import datetime

# Подключаемся к базе
conn = sqlite3.connect('app.db')
cursor = conn.cursor()

# Создаём таблицу users, если её нет
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    reset_token TEXT,
    reset_token_expires DATETIME,
    enabled_exchanges TEXT DEFAULT '',
    enabled_pairs TEXT DEFAULT '',
    update_interval INTEGER DEFAULT 1000,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Данные пользователя
username = 'daomileh'
password = '280612'

# Простейший хеш пароля (в реальном проекте используйте bcrypt или werkzeug.security)
salt = os.urandom(32).hex()
password_hash = hashlib.sha256((password + salt).encode()).hexdigest()

# Вставляем пользователя, если его ещё нет
cursor.execute('''
    INSERT OR IGNORE INTO users (username, password_hash) 
    VALUES (?, ?)
''', (username, password_hash))

conn.commit()
conn.close()

print('✅ Пользователь создан (или уже существовал).')