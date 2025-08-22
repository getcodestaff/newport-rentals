import os
import asyncio
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv()

async def run_agent():
    """Run the agent worker process"""
    process = subprocess.Popen([sys.executable, "main.py", "start"])
    return process

async def run_health_check():
    """Run the health check server"""
    process = subprocess.Popen([sys.executable, "health_check.py"])
    return process

async def main():
    print("Starting agent services...")
    
    # Start health check first for faster deployment
    health_process = await run_health_check()
    print("Health check server started.")
    
    # Wait a moment before starting the heavy agent process
    await asyncio.sleep(2)
    agent_process = await run_agent()
    
    print("Both services started. Agent is running in background.")
    
    try:
        # Keep the main process running
        while True:
            await asyncio.sleep(1)
            
            # Check if processes are still running
            if agent_process.poll() is not None:
                print("Agent process died, restarting...")
                agent_process = await run_agent()
                
            if health_process.poll() is not None:
                print("Health check process died, restarting...")
                health_process = await run_health_check()
                
    except KeyboardInterrupt:
        print("Shutting down...")
        agent_process.terminate()
        health_process.terminate()
        agent_process.wait()
        health_process.wait()

if __name__ == "__main__":
    asyncio.run(main())
