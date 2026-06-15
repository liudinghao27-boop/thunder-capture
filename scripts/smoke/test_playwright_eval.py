import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Test 1: Arrow function without IIFE
        try:
            res = await page.evaluate("async () => { return 1; }")
            print("Test 1 Result:", res)
        except Exception as e:
            print("Test 1 Error:", e)
            
        # Test 2: Arrow function with IIFE
        try:
            res = await page.evaluate("(async () => { return 2; })()")
            print("Test 2 Result:", res)
        except Exception as e:
            print("Test 2 Error:", e)
            
        # Test 3: Raw expression
        try:
            res = await page.evaluate("Promise.resolve(3)")
            print("Test 3 Result:", res)
        except Exception as e:
            print("Test 3 Error:", e)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
