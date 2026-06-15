import sqlite3

conn = sqlite3.connect('data/thunder.db')
c = conn.cursor()

# Check consumer state
c.execute("SELECT * FROM consumer_state WHERE consumer_id='xiaomi-main'")
row = c.fetchone()
if row:
    print("xiaomi-main state:", dict(zip([col[0] for col in c.description], row)))
else:
    print("xiaomi-main has no consumer state in DB.")

# Check pending tasks
c.execute("SELECT count(*) FROM task_queue WHERE status='pending'")
print("Pending tasks:", c.fetchone()[0])

conn.close()
