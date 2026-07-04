import asyncio
from playwright.async_api import async_playwright
from indeed_jobs import get_indeed_context, is_logged_in_indeed

async def test():
    async with async_playwright() as p:
        ctx = await get_indeed_context(p, headless=True)
        page = await ctx.new_page()
        ok = await is_logged_in_indeed(page)
        print("Final URL:", page.url)
        print("Logged in:", ok)
        await ctx.close()

asyncio.run(test())
