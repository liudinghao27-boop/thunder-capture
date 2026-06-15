import sys

# Force standard output to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

def read_log():
    try:
        # Try UTF-16LE which PowerShell > redirection creates
        content = open('server.log', encoding='utf-16le').read()
    except Exception as e:
        try:
            content = open('server.log', encoding='utf-8').read()
        except Exception as e2:
            print("Failed to read log:", e, e2)
            return
            
    print(f"Log length: {len(content)} characters")
    print("--- Last 100 lines of log ---")
    lines = content.splitlines()
    for line in lines[-100:]:
        print(line)

if __name__ == '__main__':
    read_log()
