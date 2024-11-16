import logging
from typing import Dict
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .config_manager import ConfigManager
from .channel_bot import ChannelBot

logger = logging.getLogger('AdminBot')

class AdminBot:
    def __init__(self, config_manager: ConfigManager, channel_bot: ChannelBot):
        self.config_manager = config_manager
        self.channel_bot = channel_bot
        self.admin_ids = set(config_manager.config['admin_ids'])
        self.app = None

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_ids

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not self.is_admin(update.effective_user.id):
            return

        await update.message.reply_text(
            "Welcome to Channel Bot Admin Panel!\n\n"
            "Available commands:\n"
            "/add <target> [source1,source2] <interval> - Add new channel\n"
            "/remove <target> - Remove channel\n"
            "/list - List all channels\n"
            "/status - Show bot status"
        )

    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command"""
        if not self.is_admin(update.effective_user.id):
            return

        try:
            args = context.args
            if len(args) < 3:
                await update.message.reply_text(
                    "Usage: /add <target> <source1,source2,...> <interval> [mistral_agent_id]\n"
                    "Example: /add @targetChannel @source1,@source2 60 agent_123\n"
                    "Note: mistral_agent_id is optional"
                )
                return

            target = args[0]
            sources = args[1].split(',')
            
            # Clean up channel usernames
            target = target.strip('@')
            sources = [s.strip('@') for s in sources]
            
            try:
                interval = int(args[2])
                if interval < 1:
                    raise ValueError("Interval must be greater than 0")
            except ValueError:
                await update.message.reply_text("Interval must be a positive number of minutes")
                return

            # Get optional mistral agent ID
            mistral_agent_id = args[3] if len(args) > 3 else None

            # Validate channels before adding
            status_msg = await update.message.reply_text("Validating channels...")
            
            # Validate target channel
            try:
                target_chat = await self.channel_bot.app.get_chat(target)
                if not str(target_chat.type.value) in ["channel", "supergroup"]:
                    await status_msg.edit_text(f"Error: {target} is not a channel")
                    return
                    
                # Check bot's admin rights in target channel
                bot_member = await self.channel_bot.app.get_chat_member(target_chat.id, "me")
                if not bot_member.privileges.can_post_messages:
                    await status_msg.edit_text(f"Error: Bot needs admin rights in {target}")
                    return
            except Exception as e:
                logger.error(e)
                await status_msg.edit_text(f"Error: Could not access target channel {target}. Make sure:\n"
                                        "1. The channel exists\n"
                                        "2. The bot is added as an admin\n"
                                        "3. The channel username is correct")
                return

            # Validate and subscribe to source channels
            invalid_sources = []
            for source in sources:
                try:
                    source_chat = await self.channel_bot.app.get_chat(source)
                    if not source_chat.type.value in ["channel", "supergroup"]:
                        invalid_sources.append(f"{source} (not a channel)")
                        continue
                    
                    try:
                        await self.channel_bot.app.join_chat(source)
                    except Exception as e:
                        invalid_sources.append(f"{source} (couldn't join)")
                except Exception as e:
                    invalid_sources.append(f"{source} (not found)")

            if invalid_sources:
                await status_msg.edit_text(
                    f"Error: Following sources are invalid:\n"
                    f"{chr(10).join(invalid_sources)}"
                )
                return

            # All validations passed, add the channel
            if self.config_manager.add_channel(target, sources, interval, mistral_agent_id):
                await self.channel_bot.add_channel(target, sources, interval, mistral_agent_id)
                await status_msg.edit_text(
                    f"✅ Channel {target} added successfully!\n\n"
                    f"• Target: @{target}\n"
                    f"• Sources: {', '.join('@' + s for s in sources)}\n"
                    f"• Interval: {interval} minutes\n"
                    f"• Mistral Agent: {mistral_agent_id or 'default'}"
                )
            else:
                await status_msg.edit_text(f"Channel {target} already exists!")

        except Exception as e:
            logger.error(f"Error in add_channel_command: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def remove_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command"""
        if not self.is_admin(update.effective_user.id):
            return

        try:
            if not context.args:
                await update.message.reply_text("Usage: /remove <target>")
                return

            target = context.args[0]
            if self.config_manager.remove_channel(target):
                await self.channel_bot.remove_channel(target)
                await update.message.reply_text(f"Channel {target} removed successfully!")
            else:
                await update.message.reply_text(f"Channel {target} not found!")

        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)}")

    async def list_channels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command"""
        if not self.is_admin(update.effective_user.id):
            return

        channels = self.config_manager.channels
        if not channels:
            await update.message.reply_text("No channels configured!")
            return

        response = "Configured channels:\n\n"
        for channel in channels:
            response += f"Target: {channel.target_channel}\n"
            response += f"Sources: {', '.join(channel.source_channels)}\n"
            response += f"Interval: {channel.post_interval_minutes} minutes\n\n"

        await update.message.reply_text(response)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        if not self.is_admin(update.effective_user.id):
            return

        status = await self.channel_bot.get_status()
        await update.message.reply_text(status)

    async def run(self):
        """Run the admin bot"""
        self.app = Application.builder().token(self.config_manager.config['admin_bot_token']).build()

        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("add", self.add_channel_command))
        self.app.add_handler(CommandHandler("remove", self.remove_channel_command))
        self.app.add_handler(CommandHandler("list", self.list_channels_command))
        self.app.add_handler(CommandHandler("status", self.status_command))

        logger.info("Starting admin bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    async def stop(self):
        """Stop the admin bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
