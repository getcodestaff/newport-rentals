import os
import asyncio
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

async def health_check(request):
    return web.json_response({"status": "healthy", "service": "agent"})

async def main():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.getenv("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"Health check server running on port {port}")
    
    # Keep the server running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
