import sqlite3

def cleanup():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("DELETE FROM task_queue WHERE industry_slug='test_cooldown'")
    conn.commit()
    c.execute("SELECT count(*) FROM task_queue")
    count = c.fetchone()[0]
    print(f"Cleanup complete. Remaining tasks in database: {count}")
    conn.close()

if __name__ == '__main__':
    cleanup()
