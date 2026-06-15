import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect_ind():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("SELECT * FROM sa_industries")
    rows = c.fetchall()
    
    c.execute("PRAGMA table_info(sa_industries)")
    cols = [col[1] for col in c.fetchall()]
    
    for row in rows:
        d = dict(zip(cols, row))
        print(f"\nIndustry: {d['name']}")
        for k, v in d.items():
            print(f"  {k}: {repr(v)}")
            
    conn.close()

if __name__ == '__main__':
    inspect_ind()
