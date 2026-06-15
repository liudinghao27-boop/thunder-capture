"""Reset: delete all users and create admin/admin123456"""
import psycopg2

conn = psycopg2.connect(
    "postgresql://thunder:thunder123@localhost:5432/thunder",
    connect_timeout=5,
)
cur = conn.cursor()

cur.execute("SELECT username FROM sa_users")
rows = cur.fetchall()
print(f"Existing: {len(rows)}")

cur.execute("DELETE FROM sa_users")

# Verified bcrypt hash for "admin123456"
PW_HASH = "$2b$12$8denfoUx1zbTO5j0ERWH0OYuyf1FbKwy7DWfD6dyid2Te.FG8bIVm"

cur.execute(
    "INSERT INTO sa_users (id, username, password_hash, is_active, created_at) "
    "VALUES (gen_random_uuid(), 'admin', %s, true, now())",
    (PW_HASH,),
)
conn.commit()
cur.execute("SELECT username FROM sa_users")
print(f"After reset: {[r[0] for r in cur.fetchall()]}")
conn.close()
print("Done. admin / admin123456")


