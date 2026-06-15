import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def count_bloggers():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("SELECT industry_slug, count(*) FROM target_bloggers GROUP BY industry_slug")
    print("Blogger count by industry:")
    for row in c.fetchall():
        print(f"  {row[0]}: {row[1]} bloggers")
    conn.close()

if __name__ == '__main__':
    count_bloggers()
