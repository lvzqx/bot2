import sqlite3

def list_tables():
    conn = sqlite3.connect('thoughts.db')
    cursor = conn.cursor()
    
    # テーブル一覧を取得
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    print("利用可能なテーブル:")
    for table in tables:
        print(f"- {table[0]}")
        
        # 各テーブルのカラム情報を表示
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        print("  カラム:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        print()
    
    conn.close()

if __name__ == "__main__":
    list_tables()
