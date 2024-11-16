import asyncio
import logging
from typing import Dict, Optional
from mistralai import Mistral
from pyrogram import Client
from pyrogram.types import Message
from .channel_manager import ChannelManager
from .config_manager import ConfigManager
from .models import ChannelConfig

logger = logging.getLogger('ChannelBot')

class ChannelBot:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.managers: Dict[str, ChannelManager] = {}
        self.running_tasks = set()
        self.is_running = True
        
        # Initialize Mistral client
        self.mistral = Mistral(api_key=config_manager.config['mistral_api_key'])
        
        # Initialize Pyrogram client
        self.app = Client(
            "channel_bot",
            api_id=config_manager.config['tg_api_id'],
            api_hash=config_manager.config['tg_api_hash']
        )
        
        # Initialize managers for existing channels
        self.initialize_managers()

    def initialize_managers(self):
        """Initialize channel managers from config"""
        for channel_config in self.config_manager.channels:
            self._create_manager(channel_config)

    def _create_manager(self, config: ChannelConfig) -> ChannelManager:
        """Create new channel manager"""
        manager = ChannelManager(
            app=self.app,
            mistral_client=self.mistral,
            config=config
        )
        self.managers[config.target_channel] = manager
        return manager

    async def add_channel(self, target_channel: str, source_channels: list, interval: int, mistral_agent_id: Optional[str] = None, theme: Optional[str] = None) -> bool:
        """Add new channel to bot"""
        try:
            # Get or create channel config
            channel_config = ChannelConfig(
                source_channels=source_channels,
                target_channel=target_channel,
                mistral_agent_id=mistral_agent_id or self.config_manager.config['default_mistral_agent'],
                channel_theme=theme or '',
                post_interval_minutes=interval
            )
            
            # Create and start manager
            manager = self._create_manager(channel_config)
            task = asyncio.create_task(manager.start_posting_loop())
            self.running_tasks.add(task)
            task.add_done_callback(self.running_tasks.discard)
            
            logger.info(f"Added new channel: {target_channel}")
            return True
        except Exception as e:
            logger.error(f"Error adding channel {target_channel}: {e}")
            return False

    async def remove_channel(self, target_channel: str) -> bool:
        """Remove channel from bot"""
        try:
            manager = self.managers.get(target_channel)
            if manager:
                await manager.stop()
                del self.managers[target_channel]
                logger.info(f"Removed channel: {target_channel}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing channel {target_channel}: {e}")
            return False

    async def get_status(self) -> str:
        """Get bot status information"""
        try:
            status_lines = ["Channel Bot Status:"]
            status_lines.append(f"\nActive Channels: {len(self.managers)}")
            
            for target, manager in self.managers.items():
                status_lines.append(f"\n{target}:")
                status_lines.append(f"- Sources: {', '.join(manager.config.source_channels)}")
                status_lines.append(f"- Interval: {manager.config.post_interval_minutes} minutes")
                status_lines.append(f"- Collected posts: {len(manager.posts)}")
                status_lines.append(f"- Last post: {manager.last_post_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            return "\n".join(status_lines)
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return "Error getting bot status"

    async def handle_new_message(self, client: Client, message: Message):
        """Handle incoming messages from all channels"""
        try:
            if not message.chat:
                return
                
            chat_username = message.chat.username
            if not chat_username:
                return
                
            for manager in self.managers.values():
                if chat_username in manager.config.source_channels:
                    await manager.process_channel_post(message)
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def initialize(self):
        """Initialize all channel managers and start their tasks"""
        logger.info("Initializing channel managers...")
        for channel_config in self.config_manager.channels:
            await self.add_channel(
                channel_config.target_channel,
                channel_config.source_channels,
                channel_config.post_interval_minutes,
                channel_config.mistral_agent_id
            )
        logger.info(f"Initialized {len(self.managers)} channel managers")

    async def run(self):
        """Run the channel bot"""
        try:
            logger.info("Starting Channel Bot...")
            
            if not self.app:
                logger.error("Pyrogram client not initialized")
                return
            
            # Set up message handler
            @self.app.on_message()
            async def message_handler(client, message):
                await self.handle_new_message(client, message)
            
            # Start the client if it's not already running
            if not self.app.is_connected:
                await self.app.start()
            
            # Initialize all managers
            await self.initialize()
            
            # Keep running until stopped
            while self.is_running:
                # Check for failed tasks
                failed_tasks = [t for t in self.running_tasks if t.done() and not t.cancelled()]
                for task in failed_tasks:
                    try:
                        await task  # This will raise the exception if task failed
                        logger.error(f"Task completed unexpectedly: {task}")
                    except Exception as e:
                        logger.error(f"Task failed with error: {e}")
                        # Try to restart the failed manager
                        for target, manager in self.managers.items():
                            if manager.posting_task == task:
                                logger.info(f"Restarting posting task for {target}")
                                new_task = asyncio.create_task(manager.start_posting_loop())
                                self.running_tasks.add(new_task)
                                new_task.add_done_callback(self.running_tasks.discard)
                                manager.posting_task = new_task
                
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error running channel bot: {e}")
            raise

    async def stop(self):
        """Stop the bot and all managers"""
        try:
            self.is_running = False
            
            # Cancel all running tasks
            for task in self.running_tasks:
                if not task.done():
                    task.cancel()
            
            if self.running_tasks:
                await asyncio.gather(*self.running_tasks, return_exceptions=True)
            
            # Stop all managers
            for manager in self.managers.values():
                try:
                    await manager.stop()
                except Exception as e:
                    logger.error(f"Error stopping manager: {e}")
            
            # Stop Pyrogram client if it's running
            if self.app and self.app.is_connected:
                await self.app.stop()
            
            logger.info("Channel bot stopped")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
            raise
