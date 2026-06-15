import sqlite3

def fix_model():
    conn = sqlite3.connect('data/thunder.db')
    c = conn.cursor()
    
    # Check current values
    c.execute("SELECT slug, llm_model FROM sa_industries")
    print("Before restore:", c.fetchall())
    
    # Restore both industries to use deepseek-v4-pro
    c.execute("UPDATE sa_industries SET llm_model = 'deepseek-v4-pro'")
    conn.commit()
    
    c.execute("SELECT slug, llm_model FROM sa_industries")
    print("After restore:", c.fetchall())
    
    conn.close()

if __name__ == '__main__':
    fix_model()
