import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, "c:/Users/Administrator/Desktop/shemeihuoke")
sys.stdout.reconfigure(encoding='utf-8')

def check_scan():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("SELECT username, password_hash FROM sa_users LIMIT 5")
    users = c.fetchall()
    print("Users in DB:", users)
    conn.close()
    
    print("\n--- Running scan_and_register_devices directly ---")
    import asyncio
    from sqlalchemy.orm import Session
    from server.models import SessionLocal
    from server.models.user import User
    from server.api.devices import scan_and_register_devices
    
    db = SessionLocal()
    # Get first user
    user = db.query(User).first()
    if not user:
        print("No user found in DB")
        db.close()
        return
        
    print(f"Testing scan for user: {user.username}")
    try:
        async def run_scan():
            return await scan_and_register_devices(current_user=user, db=db)
        res = asyncio.run(run_scan())
        print("Scan result:", res)
    except Exception as e:
        print("Scan failed with exception:")
        import traceback
        traceback.print_exc()
        if hasattr(e, 'detail'):
            print(f"HTTPException detail: {e.detail}")
    finally:
        db.close()

if __name__ == '__main__':
    check_scan()
