import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    
    # Inspect sa_devices
    c.execute("PRAGMA table_info(sa_devices)")
    print("sa_devices columns:", [col[1] for col in c.fetchall()])
    
    c.execute("SELECT * FROM sa_devices")
    devices = c.fetchall()
    print("Devices in database:")
    for d in devices:
        print(d)
        
    conn.close()

if __name__ == '__main__':
    inspect()
