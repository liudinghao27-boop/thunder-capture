import time
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from core.browser_orchestrator import ShadowBrowser

def main():
    print("正在启动系统原生浏览器...")
    user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "chrome_data"))
    browser = ShadowBrowser(user_data_dir=user_data_dir)
    
    try:
        browser.start()
        print("\n" + "="*50)
        print("1. Please log into Douyin if you haven't already.")
        print("2. IMPORTANT: Perform a search for 'test' or any keyword.")
        print("3. If a slider/CAPTCHA pops up, solve it!")
        print("4. Close the browser ONLY after you can see the search results.")
        print("="*50 + "\n")
        
        # 保持浏览器存活 120 秒供用户登录
        for i in range(120, 0, -1):
            sys.stdout.write(f"\r剩余时间: {i} 秒...")
            sys.stdout.flush()
            time.sleep(1)
            
        print("\n时间到，正在保存状态并关闭浏览器...")
    finally:
        browser.close()
        print("浏览器已关闭，状态保存成功！")

if __name__ == "__main__":
    main()
