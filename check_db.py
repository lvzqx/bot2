import sqlite3

def check_message_references():
    conn = sqlite3.connect('thoughts.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=== message_references テーブルの最初の5件 ===")
    cursor.execute('SELECT * FROM message_references LIMIT 5')
    for row in cursor.fetchall():
        print(dict(row))
    
    print("\n=== thoughts テーブルの最初の5件 ===")
    cursor.execute('SELECT * FROM thoughts LIMIT 5')
    for row in cursor.fetchall():
        print(dict(row))
    
    conn.close()

if __name__ == "__main__":
    check_message_references()
