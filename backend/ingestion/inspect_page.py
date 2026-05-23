"""Quick inspector — dumps the HTML around the SYLLABUS section."""
import asyncio
from playwright.async_api import async_playwright

URL = "https://msrit.edu/department/cse.html"

async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2000)

        # Dump the HTML of the element containing "SYLLABUS" text
        html = await page.evaluate("""
            () => {
                // Find the element with SYLLABUS text
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (el.children.length === 0 && el.textContent.trim() === 'SYLLABUS') {
                        // Return the parent and grandparent HTML
                        return (el.parentElement?.parentElement?.outerHTML || el.parentElement?.outerHTML || el.outerHTML).substring(0, 5000);
                    }
                }
                return 'SYLLABUS heading not found as leaf text';
            }
        """)
        print("=== SYLLABUS section HTML ===")
        print(html)

        # Also dump href values near the syllabus section
        hrefs = await page.evaluate("""
            () => {
                const results = [];
                const all = document.querySelectorAll('a');
                for (const a of all) {
                    const txt = a.textContent.trim();
                    const href = a.getAttribute('href') || '';
                    if (['ug first', 'ug second', 'ug third', 'ug fourth', 'pg cse', 'pg cne', 'pg ece',
                         'batch 20', 'm.tech', 'syllabus'].some(k => txt.toLowerCase().includes(k))) {
                        results.push({text: txt, href: href, class: a.className, visible: a.offsetParent !== null});
                    }
                }
                return results;
            }
        """)
        print("\n=== Syllabus-related <a> tags ===")
        for h in hrefs:
            print(f"  text={h['text']!r:40} href={h['href']!r:50} class={h['class']!r} visible={h['visible']}")

        await browser.close()

asyncio.run(run())
