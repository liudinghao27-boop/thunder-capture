import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    print("正在启动浏览器...")
    user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "chrome_data"))
    
    async with async_playwright() as p:
        # Launch persistent context which automatically uses a visible window
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 720}
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        
        print("正在打开抖音...")
        await page.goto("https://www.douyin.com/")
        
        print("\n" + "="*50)
        print("请在弹出的浏览器中登录抖音。")
        print("登录成功并确认能刷视频后，在此窗口按回车键完成并关闭。")
        print("="*50 + "\n")
        
        # Run blocking input in an executor so we don't block the async loop
        await asyncio.get_event_loop().run_in_executor(None, input, "按回车键退出...\n")
        
        await browser.close()
        print("浏览器已关闭，保存状态成功！")

if __name__ == "__main__":
    asyncio.run(main())
