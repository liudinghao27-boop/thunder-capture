import os
os.environ['THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS'] = '300'
import asyncio
from adapters.mediacrawler.runner import run_platform

async def main():
    print('=== E2E verification: keyword collection with fixed CDP ===')
    result = await run_platform('douyin', ['高考志愿'], max_authors=2)
    print(f'RESULT_COUNT={len(result)}')
    for i, c in enumerate(result[:5]):
        text = c.get('text', '')[:80]
        print(f'{i+1}. {text}...')
    # Write to file for later inspection
    with open('docs/qa/e2e_result.txt', 'w', encoding='utf-8') as f:
        f.write(f'RESULT_COUNT={len(result)}\n')
        for i, c in enumerate(result[:10]):
            f.write(f'{i+1}. {c.get("text", "")[:100]}\n')

asyncio.run(main())
