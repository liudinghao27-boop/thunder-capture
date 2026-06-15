import sys

sys.stdout.reconfigure(encoding='utf-8')

def read_task_log():
    path = r"C:\Users\Administrator\.gemini\antigravity\brain\1e844de7-6a73-467e-a9c2-c0a31c9ae1e4\.system_generated\tasks\task-1944.log"
    try:
        content = open(path, encoding='utf-8').read()
    except Exception as e:
        try:
            content = open(path, encoding='utf-16le').read()
        except Exception as e2:
            print("Failed to read log:", e, e2)
            return
            
    print(f"Task Log length: {len(content)} characters")
    print("--- Last 200 lines of Task Log ---")
    lines = content.splitlines()
    for line in lines[-200:]:
        print(line)

if __name__ == '__main__':
    read_task_log()
