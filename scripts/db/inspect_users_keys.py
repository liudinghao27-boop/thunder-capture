import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

def inspect_users_keys():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    c.execute("SELECT id, username, deepseek_key, zhipu_key, openai_key FROM sa_users")
    for row in c.fetchall():
        print(f"User: {row[1]} (id: {row[0]})")
        print(f"  DeepSeek Key: {repr(row[2])}")
        print(f"  Zhipu Key: {repr(row[3])}")
        print(f"  OpenAI Key: {repr(row[4])}")
    conn.close()

if __name__ == '__main__':
    inspect_users_keys()
