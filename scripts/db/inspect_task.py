import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect_task(task_id):
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("SELECT * FROM task_queue WHERE id=?", (task_id,))
    row = c.fetchone()
    if not row:
        print(f"Task #{task_id} not found")
        conn.close()
        return
        
    c.execute("PRAGMA table_info(task_queue)")
    cols = [col[1] for col in c.fetchall()]
    
    task_dict = dict(zip(cols, row))
    print(f"Task #{task_id} details:")
    for k, v in task_dict.items():
        print(f"  {k}: {repr(v)}")
        
    conn.close()

if __name__ == '__main__':
    inspect_task(998)
