import asyncio
import logging
from datetime import datetime
from typing import List, Optional
from mistralai import Mistral
from pyrogram import Client
from pyrogram.types import Message
from .models import ChannelPost, ChannelConfig

logger = logging.getLogger('ChannelManager')

class ChannelManager:
    def __init__(self, 
                 app: Client, 
                 mistral_client: Mistral, 
                 config: ChannelConfig):
        self.app = app
        self.mistral = mistral_client
        self.config = config
        self.posts: List[ChannelPost] = []
        self.last_post_time = datetime.now()
        self.post_lock = asyncio.Lock()
        self.is_running = True
        self.posting_in_progress = False
        
        logger.info(f"Initialized channel manager for {config.target_channel}")
        logger.info(f"Monitoring channels: {', '.join(config.source_channels)}")

    async def process_channel_post(self, message: Message):
        """Process new post from source channel with enhanced logging and checks"""
        try:
            if not message.chat or not message.chat.username:
                logger.debug(f"Skipping message: Missing chat or username")
                return

            if message.chat.username not in self.config.source_channels:
                logger.debug(f"Skipping message: Channel {message.chat.username} not in source list")
                return
            
            logger.debug(f"""
            Processing message:
            ID: {message.id}
            Chat: {message.chat.username}
            Type: {message.media_group_id if message.media_group_id else 'single message'}
            Has text: {bool(message.text)}
            Has caption: {bool(message.caption)}
            Service message: {bool(message.service)}
            Is sponsored: {hasattr(message, 'sponsor') and bool(message.sponsor)}
            Media type: {message.media.value if message.media else 'none'}
            """)

            if message.service:
                logger.debug(f"Skipping service message type: {message.service}")
                return
            
            if hasattr(message, 'sponsor') and message.sponsor:
                logger.debug("Skipping sponsored message")
                return
            
            async with self.post_lock:
                text = self._extract_message_text(message)
                media_type = self._detect_media_type(message)
                
                if text or media_type:
                    post = ChannelPost(
                        channel_title=message.chat.title or message.chat.username,
                        text=text,
                        date=message.date,
                        link=message.link,
                        media_type=media_type
                    )
                    self.posts.append(post)
                    logger.info(f"Successfully saved post from {post.channel_title}")
                    logger.debug(f"Post content length: {len(text) if text else 0}, Media: {media_type}")
                else:
                    logger.debug("Skipping message: No content to save")

        except Exception as e:
            logger.error(f"Error processing channel post: {str(e)}", exc_info=True)

    def _extract_message_text(self, message: Message) -> Optional[str]:
        """Extract text content from message with fallback to caption"""
        text = message.text or message.caption
        
        if not text and message.media:
            if message.photo and message.caption:
                text = message.caption
            elif message.video and message.caption:
                text = message.caption
            elif message.document and message.caption:
                text = message.caption
        
        return text.strip() if text else None

    def _detect_media_type(self, message: Message) -> Optional[str]:
        """Detect media type from message"""
        if message.media_group_id:
            if message.photo:
                return "photo_group"
            elif message.video:
                return "video_group"
        elif message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.document:
            return "document"
        elif message.animation:
            return "animation"
        elif message.sticker:
            return "sticker"
        
        return None

    def _prepare_digest_data(self) -> dict:
        """Prepare data for digest creation"""
        return {
            'timestamp': datetime.now().isoformat(),
            'channel_theme': self.config.channel_theme,
            'source_channels': self.config.source_channels,
            'posts': [vars(post) for post in self.posts],
            'stats': {
                'total_posts': len(self.posts),
                'channels_count': len(self.config.source_channels)
            }
        }

    async def create_and_post_digest(self):
        """Create and post digest to target channel"""
        if self.posting_in_progress:
            return
            
        self.posting_in_progress = True
        async with self.post_lock:
            try:
                if not self.posts:
                    logger.info(f"No posts to digest for {self.config.target_channel}")
                    self.last_post_time = datetime.now()  # Reset timer if no posts
                    return

                digest_data = self._prepare_digest_data()
                
                logger.info(f"Requesting digest from Mistral for {self.config.target_channel}...")
                chat_response = self.mistral.agents.complete(
                    agent_id=self.config.mistral_agent_id,
                    messages=[{
                        "role": "user",
                        "content": f"Create an engaging and thematic digest channel post based on this data: {digest_data}"
                    }]
                )
                
                digest_text = chat_response.choices[0].message.content
                logger.info(f"Got digest from Mistral for {self.config.target_channel}")
                
                try:
                    await self.app.send_message(
                        chat_id=self.config.target_channel,
                        text=digest_text
                    )
                    logger.info(f"Successfully posted digest to {self.config.target_channel}")
                    
                    self.posts.clear()
                    self.last_post_time = datetime.now()
                except Exception as e:
                    logger.error(f"Failed to send message to {self.config.target_channel}: {e}")
                    
            except Exception as e:
                logger.error(f"Failed to create or post digest: {e}")
            finally:
                self.posting_in_progress = False

    async def start_posting_loop(self):
        """Start posting loop"""
        logger.info(f"Starting posting loop for {self.config.target_channel}")
        try:
            last_check_time = datetime.now()
            
            while self.is_running:
                current_time = datetime.now()
                minutes_elapsed = (current_time - self.last_post_time).total_seconds() / 60
                
                if minutes_elapsed >= self.config.post_interval_minutes and not self.posting_in_progress:
                    logger.info(f"Time to create digest for {self.config.target_channel}")
                    await self.create_and_post_digest()
                
                # Log status every minute
                if (current_time - last_check_time).total_seconds() >= 60:
                    logger.info(
                        f"Channel {self.config.target_channel} - "
                        f"Minutes since last post: {minutes_elapsed:.1f}/{self.config.post_interval_minutes} "
                        f"Posts collected: {len(self.posts)}"
                    )
                    last_check_time = current_time
                
                await asyncio.sleep(10)  # Check more frequently
                
        except asyncio.CancelledError:
            logger.info(f"Posting loop cancelled for {self.config.target_channel}")
            raise
        except Exception as e:
            logger.error(f"Error in posting loop for {self.config.target_channel}: {e}")
            raise

    async def stop(self):
        """Stop the manager"""
        self.is_running = False
        await self.create_and_post_digest()  # Final digest
