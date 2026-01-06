import sqlite3
import os
from datetime import datetime

# データベース接続
conn = sqlite3.connect('thoughts.db')
cursor = conn.cursor()

# テーブル作成
cursor.execute('''
    CREATE TABLE IF NOT EXISTS thoughts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        category TEXT,
        image_url TEXT,
        is_anonymous BOOLEAN DEFAULT 0,
        is_private BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL,
        display_name TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS message_references (
        post_id INTEGER PRIMARY KEY,
        message_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        FOREIGN KEY (post_id) REFERENCES thoughts (id) ON DELETE CASCADE
    )
''')

# インデックス作成
cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_user_id ON thoughts (user_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_created_at ON thoughts (created_at)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_category ON thoughts (category)')

# パフォーマンス最適化
cursor.execute('PRAGMA journal_mode=WAL')
cursor.execute('PRAGMA synchronous=NORMAL')
cursor.execute('PRAGMA cache_size=-2000')

conn.commit()
conn.close()
print('データベースを初期化しました')
