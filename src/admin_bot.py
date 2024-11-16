import logging
from typing import Dict, List, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from .config_manager import ConfigManager
from .channel_bot import ChannelBot
from .models import ChannelConfig

logger = logging.getLogger('AdminBot')

(
    CHOOSE_ACTION,
    ADD_TARGET,
    ADD_SOURCES,
    ADD_INTERVAL,
    ADD_AGENT,
    ADD_THEME,
    EDIT_CHANNEL,
    EDIT_FIELD,
    CONFIRM_DELETE
) = range(8)

class AdminBot:
    def __init__(self, config_manager: ConfigManager, channel_bot: ChannelBot):
        self.config_manager = config_manager
        self.channel_bot = channel_bot
        self.admin_ids = set(config_manager.config['admin_ids'])
        self.app = None
        
        self.temp_data: Dict[int, dict] = {}

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_ids

    def get_main_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Create main menu keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"),
                InlineKeyboardButton("📋 List Channels", callback_data="list_channels")
            ],
            [
                InlineKeyboardButton("📊 Show Status", callback_data="show_status")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_channel_actions_keyboard(self, channel: str) -> InlineKeyboardMarkup:
        """Create keyboard for channel actions"""
        keyboard = [
            [
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{channel}"),
                InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{channel}")
            ],
            [InlineKeyboardButton("« Back to List", callback_data="list_channels")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_edit_fields_keyboard(self, channel: str) -> InlineKeyboardMarkup:
        """Create keyboard for editing channel fields"""
        keyboard = [
            [InlineKeyboardButton("📺 Source Channels", callback_data=f"edit_sources_{channel}")],
            [InlineKeyboardButton("⏱ Post Interval", callback_data=f"edit_interval_{channel}")],
            [InlineKeyboardButton("🤖 Mistral Agent", callback_data=f"edit_agent_{channel}")],
            [InlineKeyboardButton("🎯 Channel Theme", callback_data=f"edit_theme_{channel}")],
            [InlineKeyboardButton("« Back", callback_data=f"channel_info_{channel}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not self.is_admin(update.effective_user.id):
            return

        await update.message.reply_text(
            "Welcome to Channel Bot Admin Panel! 🎉\n\n"
            "Use the menu below to manage your channels:",
            reply_markup=self.get_main_menu_keyboard()
        )
        return CHOOSE_ACTION
    
    async def validate_channels(
            self, 
            target: str, 
            sources: List[str]
        ) -> Tuple[bool, str, List[str]]:
            """
            Validate target and source channels
            Returns: (success, error_message, invalid_sources)
            """
            # Validate target channel
            try:
                target_chat = await self.channel_bot.app.get_chat(target)
                if not str(target_chat.type.value) in ["channel", "supergroup"]:
                    return False, f"Error: @{target} is not a channel", []
                if target.count("@") != 0 or target.count(" ") != 0:
                    return False, f"Error: @{target} is not a valid channel name", []
                          
                # Check bot's admin rights in target channel
                bot_member = await self.channel_bot.app.get_chat_member(target_chat.id, "me")
                if not bot_member.privileges.can_post_messages:
                    return False, f"Error: Bot needs admin rights in @{target}", []
            except Exception as e:
                logger.error(e)
                return False, (
                    f"Error: Could not access target channel @{target}. Make sure:\n"
                    "1. The channel exists\n"
                    "2. The bot is added as an admin\n"
                    "3. The channel username is correct"
                ), []

            # Validate source channels
            invalid_sources = []
            for source in sources:
                try:
                    source_chat = await self.channel_bot.app.get_chat(source)
                    if not source_chat.type.value in ["channel", "supergroup"]:
                        invalid_sources.append(f"@{source} (not a channel)")
                        continue
                    if source.count("@") != 0 or target.count(" ") != 0:
                        invalid_sources.append(f"@{source} (not a valid channel name)")
                        continue
                    try:
                        await self.channel_bot.app.join_chat(source)
                    except Exception as e:
                        invalid_sources.append(f"@{source} (couldn't join)")
                except Exception as e:
                    invalid_sources.append(f"@{source} (not found)")

            if invalid_sources:
                error_msg = "Error: Following sources are invalid:\n" + "\n".join(invalid_sources)
                return False, error_msg, invalid_sources

            return True, "", []

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        if not self.is_admin(query.from_user.id):
            return ConversationHandler.END

        if query.data == "add_channel":
            await query.edit_message_text(
                "Please send me the target channel username\n"
                "(e.g., @mychannel or mychannel)",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Cancel", callback_data="cancel")
                ]])
            )
            return ADD_TARGET

        elif query.data == "list_channels":
            channels = self.config_manager.channels
            if not channels:
                await query.edit_message_text(
                    "No channels configured! 😕\n\n"
                    "Use Add Channel button to configure your first channel.",
                    reply_markup=self.get_main_menu_keyboard()
                )
                return CHOOSE_ACTION

            text = "📺 Configured channels:\n\n"
            keyboard = []
            for channel in channels:
                text += f"• @{channel.target_channel}\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"@{channel.target_channel}", 
                        callback_data=f"channel_info_{channel.target_channel}"
                    )
                ])
            keyboard.append([InlineKeyboardButton("« Main Menu", callback_data="main_menu")])
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CHOOSE_ACTION

        elif query.data.startswith("channel_info_"):
            channel_name = query.data.replace("channel_info_", "")
            channel = next((c for c in self.config_manager.channels 
                          if c.target_channel == channel_name), None)
            
            if channel:
                text = (
                    f"📺 Channel: @{channel.target_channel}\n\n"
                    f"📡 Sources: {', '.join('@' + s for s in channel.source_channels)}\n"
                    f"⏱ Interval: {channel.post_interval_minutes} minutes\n"
                    f"🤖 Mistral Agent: {channel.mistral_agent_id or 'default'}"
                )
                await query.edit_message_text(
                    text,
                    reply_markup=self.get_channel_actions_keyboard(channel_name)
                )
            return CHOOSE_ACTION

        elif query.data.startswith("edit_"):
            if "_sources_" in query.data or "_interval_" in query.data or "_agent_" in query.data:
                channel_name = query.data.split("_")[-1]
                field_type = query.data.split("_")[1]
                
                self.temp_data[query.from_user.id] = {
                    "channel": channel_name,
                    "field": field_type
                }
                
                if field_type == "sources":
                    await query.edit_message_text(
                        "Please send me the new source channels (comma-separated)\n"
                        "Example: @channel1, @channel2, @channel3",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Cancel", callback_data=f"channel_info_{channel_name}")
                        ]])
                    )
                elif field_type == "interval":
                    await query.edit_message_text(
                        "Please send me the new post interval in minutes\n"
                        "Example: 60",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Cancel", callback_data=f"channel_info_{channel_name}")
                        ]])
                    )
                elif field_type == "agent":
                    await query.edit_message_text(
                        "Please send me the new Mistral agent ID\n"
                        "Send 'default' to use the default agent",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Cancel", callback_data=f"channel_info_{channel_name}")
                        ]])
                    )
                return EDIT_FIELD
            
            channel_name = query.data.replace("edit_", "")
            await query.edit_message_text(
                f"What would you like to edit for @{channel_name}?",
                reply_markup=self.get_edit_fields_keyboard(channel_name)
            )
            return EDIT_CHANNEL

        elif query.data.startswith("delete_"):
            channel_name = query.data.replace("delete_", "")
            await query.edit_message_text(
                f"Are you sure you want to delete @{channel_name}?",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Yes", callback_data=f"confirm_delete_{channel_name}"),
                        InlineKeyboardButton("❌ No", callback_data=f"channel_info_{channel_name}")
                    ]
                ])
            )
            return CONFIRM_DELETE

        elif query.data.startswith("confirm_delete_"):
            channel_name = query.data.replace("confirm_delete_", "")
            if await self.channel_bot.remove_channel(channel_name):
                self.config_manager.remove_channel(channel_name)
                await query.edit_message_text(
                    f"Channel @{channel_name} has been deleted! ✅",
                    reply_markup=self.get_main_menu_keyboard()
                )
            else:
                await query.edit_message_text(
                    f"Failed to delete channel @{channel_name} ❌",
                    reply_markup=self.get_main_menu_keyboard()
                )
            return CHOOSE_ACTION

        elif query.data == "show_status":
            status = await self.channel_bot.get_status()
            await query.edit_message_text(
                status,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Main Menu", callback_data="main_menu")
                ]])
            )
            return CHOOSE_ACTION

        elif query.data == "main_menu":
            await query.edit_message_text(
                "Main Menu:",
                reply_markup=self.get_main_menu_keyboard()
            )
            return CHOOSE_ACTION

        elif query.data == "cancel":
            await query.edit_message_text(
                "Operation cancelled.",
                reply_markup=self.get_main_menu_keyboard()
            )
            return CHOOSE_ACTION

    async def handle_target_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle target channel input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        target = update.message.text.strip('@')
        
        status_msg = await update.message.reply_text("Validating target channel...")
        is_valid, error_msg, _ = await self.validate_channels(target, [])
        
        if not is_valid:
            await status_msg.edit_text(error_msg)
            return ADD_TARGET
            
        await status_msg.delete()
        self.temp_data[update.effective_user.id] = {"target": target}

        await update.message.reply_text(
            "Please send me the source channels (comma-separated)\n"
            "Example: @channel1, @channel2, @channel3",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Cancel", callback_data="cancel")
            ]])
        )
        return ADD_SOURCES

    async def handle_sources_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle source channels input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        sources = [s.strip('@') for s in update.message.text.split(', ')]
        
        status_msg = await update.message.reply_text("Validating source channels...")
        is_valid, error_msg, invalid_sources = await self.validate_channels(
            self.temp_data[update.effective_user.id]["target"],
            sources
        )
        
        if not is_valid:
            await status_msg.edit_text(error_msg)
            return ADD_SOURCES
            
        await status_msg.delete()
        self.temp_data[update.effective_user.id]["sources"] = sources

        await update.message.reply_text(
            "Please send me the post interval in minutes\n"
            "Example: 60",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Cancel", callback_data="cancel")
            ]])
        )
        return ADD_INTERVAL

    async def handle_interval_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle interval input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        try:
            interval = int(update.message.text)
            if interval < 1:
                raise ValueError()
                
            self.temp_data[update.effective_user.id]["interval"] = interval

            await update.message.reply_text(
                "Please send me the Mistral agent ID\n"
                "Or send 'skip' to use the default agent",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Cancel", callback_data="cancel")
                ]])
            )
            return ADD_AGENT
            
        except ValueError:
            await update.message.reply_text(
                "Please send a valid number greater than 0\n"
                "Example: 60"
            )
            return ADD_INTERVAL

    async def handle_agent_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Mistral agent ID input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        agent_id = None if update.message.text.lower() == 'skip' else update.message.text
        self.temp_data[update.effective_user.id]["agent_id"] = agent_id

        await update.message.reply_text(
            "Please send me the channel theme\n"
            "This helps create more relevant digests",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Cancel", callback_data="cancel")
            ]])
        )
        return ADD_THEME
    
    async def handle_theme_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle channel theme input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        theme = update.message.text
        data = self.temp_data[update.effective_user.id]

        try:
            if self.config_manager.add_channel(
                data["target"],
                data["sources"],
                data["interval"],
                data["agent_id"],
                theme
            ):
                success = await self.channel_bot.add_channel(
                    data["target"],
                    data["sources"],
                    data["interval"],
                    data["agent_id"],
                    theme
                )
                
                if success:
                    await update.message.reply_text(
                        f"✅ Channel @{data['target']} added successfully!\n\n"
                        f"• Sources: {', '.join('@' + s for s in data['sources'])}\n"
                        f"• Interval: {data['interval']} minutes\n"
                        f"• Agent: {data['agent_id'] or 'default'}\n"
                        f"• Theme: {theme}",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                else:
                    self.config_manager.remove_channel(data["target"])
                    raise Exception("Failed to initialize channel manager")
            else:
                raise Exception("Failed to add channel configuration")
                
        except Exception as e:
            await update.message.reply_text(
                f"Failed to add channel: {str(e)}",
                reply_markup=self.get_main_menu_keyboard()
            )
        
        del self.temp_data[update.effective_user.id]
        return CHOOSE_ACTION

    async def handle_edit_field_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle field editing input"""
        if not self.is_admin(update.effective_user.id):
            return ConversationHandler.END

        data = self.temp_data.get(update.effective_user.id)
        if not data:
            await update.message.reply_text(
                "Something went wrong. Please try again.",
                reply_markup=self.get_main_menu_keyboard()
            )
            return CHOOSE_ACTION

        channel_name = data["channel"]
        channel = self.config_manager.get_channel_config(channel_name)
        if not channel:
            await update.message.reply_text(
                "Channel not found. Please try again.",
                reply_markup=self.get_main_menu_keyboard()
            )
            return CHOOSE_ACTION

        try:
            new_config = ChannelConfig(
                source_channels=channel.source_channels.copy(),
                target_channel=channel.target_channel,
                mistral_agent_id=channel.mistral_agent_id,
                post_interval_minutes=channel.post_interval_minutes,
                channel_theme=channel.channel_theme
            )

            if data["field"] == "sources":
                new_sources = [s.strip('@') for s in update.message.text.split(',')]
                
                status_msg = await update.message.reply_text("Validating source channels...")
                is_valid, error_msg, invalid_sources = await self.validate_channels(
                    channel_name,
                    new_sources
                )
                
                if not is_valid:
                    await status_msg.edit_text(error_msg)
                    return EDIT_FIELD
                    
                await status_msg.delete()
                new_config.source_channels = new_sources
                success_msg = f"Source channels updated to: {', '.join('@' + s for s in new_sources)}"
                
            elif data["field"] == "interval":
                try:
                    new_interval = int(update.message.text)
                    if new_interval < 1:
                        raise ValueError("Interval must be greater than 0")
                    new_config.post_interval_minutes = new_interval
                    success_msg = f"Post interval updated to: {new_interval} minutes"
                except ValueError:
                    await update.message.reply_text(
                        "Please enter a valid number greater than 0"
                    )
                    return EDIT_FIELD
                
            elif data["field"] == "agent":
                new_agent = None if update.message.text.lower() == 'default' else update.message.text
                new_config.mistral_agent_id = new_agent
                success_msg = f"Mistral agent updated to: {new_agent or 'default'}"
            
            if self.config_manager.remove_channel(channel_name):
                self.config_manager.add_channel(
                    new_config.target_channel,
                    new_config.source_channels,
                    new_config.post_interval_minutes,
                    new_config.mistral_agent_id,
                    new_config.channel_theme
                )
                self.config_manager.save_channels()
                
                await self.channel_bot.remove_channel(channel_name)
                await self.channel_bot.add_channel(
                    new_config.target_channel,
                    new_config.source_channels,
                    new_config.post_interval_minutes,
                    new_config.mistral_agent_id,
                    new_config.channel_theme
                )
                
                await update.message.reply_text(
                    f"✅ {success_msg}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "« Back to Channel", 
                            callback_data=f"channel_info_{channel_name}"
                        )
                    ]])
                )
            else:
                raise Exception("Failed to update channel configuration")
                
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error updating channel: {str(e)}",
                reply_markup=self.get_main_menu_keyboard()
            )
    
        del self.temp_data[update.effective_user.id]
        return CHOOSE_ACTION

    async def run(self):
        """Run the admin bot"""
        self.app = Application.builder().token(self.config_manager.config['admin_bot_token']).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                CHOOSE_ACTION: [
                    CallbackQueryHandler(self.button_callback)
                ],
                ADD_TARGET: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_target_input),
                    CallbackQueryHandler(self.button_callback, pattern="^cancel$")
                ],
                ADD_SOURCES: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_sources_input),
                    CallbackQueryHandler(self.button_callback, pattern="^cancel$")
                ],
                ADD_INTERVAL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_interval_input),
                    CallbackQueryHandler(self.button_callback, pattern="^cancel$")
                ],
                ADD_AGENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_agent_input),
                    CallbackQueryHandler(self.button_callback, pattern="^cancel$")
                ],
                ADD_THEME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_theme_input),
                    CallbackQueryHandler(self.button_callback, pattern="^cancel$")
                ],
                EDIT_CHANNEL: [
                    CallbackQueryHandler(self.button_callback)
                ],
                EDIT_FIELD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_field_input),
                    CallbackQueryHandler(self.button_callback, pattern="^channel_info_")
                ],
                CONFIRM_DELETE: [
                    CallbackQueryHandler(self.button_callback)
                ]
            },
            fallbacks=[
                CommandHandler("start", self.start_command),
                CallbackQueryHandler(self.button_callback, pattern="^cancel$")
            ]
        )

        self.app.add_handler(conv_handler)

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
