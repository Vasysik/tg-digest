import asyncio
import logging
import sys
from src.config_manager import ConfigManager
from src.channel_bot import ChannelBot
from src.admin_bot import AdminBot

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger('pyrogram').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def shutdown(channel_bot, admin_bot):
    """Cleanup tasks tied to the service's shutdown."""
    logger.info("Initiating shutdown...")
    
    logger.info("Stopping channel bot...")
    await channel_bot.stop()
    
    logger.info("Stopping admin bot...")
    await admin_bot.stop()
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    
    logger.info(f"Cancelling {len(tasks)} outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)

def handle_exception(loop, context):
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")

async def main():
    # Flag to control the main loop
    running = True
    
    try:
        # Get the current event loop
        loop = asyncio.get_running_loop()
        
        # Setup exception handler
        loop.set_exception_handler(handle_exception)
        
        # Initialize bots
        config_manager = ConfigManager()
        channel_bot = ChannelBot(config_manager)
        admin_bot = AdminBot(config_manager, channel_bot)

        # Start both bots
        await admin_bot.run()
        channel_bot_task = asyncio.create_task(channel_bot.run())
        
        logger.info("Application started. Press Ctrl+C to exit.")
        
        # Keep the application running
        while running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                running = False
                break

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        raise
    finally:
        logger.info("Shutting down...")
        await shutdown(channel_bot, admin_bot)

if __name__ == "__main__":
    if sys.platform == 'win32':
        # Set up a different event loop policy for Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Handle Ctrl+C gracefully
