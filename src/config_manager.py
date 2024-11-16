import json
from pathlib import Path
from typing import List, Optional
from .models import ChannelConfig

class ConfigManager:
    def __init__(self, config_path: str = "config.json", channels_path: str = "channels.json"):
        self.config_path = Path(config_path)
        self.channels_path = Path(channels_path)
        self.load_configs()

    def load_configs(self):
        """Load both configuration files"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        with open(self.channels_path, 'r', encoding='utf-8') as f:
            channels_data = json.load(f)
            self.channels = [ChannelConfig.from_dict(c) for c in channels_data['channels']]

    def save_channels(self):
        """Save channels configuration"""
        channels_data = {
            'channels': [c.to_dict() for c in self.channels]
        }
        with open(self.channels_path, 'w', encoding='utf-8') as f:
            json.dump(channels_data, f, indent=2, ensure_ascii=False)

    def add_channel(self, target_channel: str, source_channels: List[str], 
                   interval: int, mistral_agent_id: str = None) -> bool:
        """Add new channel configuration"""
        if not mistral_agent_id:
            mistral_agent_id = self.config['default_mistral_agent']

        new_config = ChannelConfig(
            source_channels=source_channels,
            target_channel=target_channel,
            mistral_agent_id=mistral_agent_id,
            post_interval_minutes=interval
        )
        
        # Check if channel already exists
        if any(c.target_channel == target_channel for c in self.channels):
            return False

        self.channels.append(new_config)
        self.save_channels()
        return True

    def remove_channel(self, target_channel: str) -> bool:
        """Remove channel configuration"""
        initial_length = len(self.channels)
        self.channels = [c for c in self.channels if c.target_channel != target_channel]
        
        if len(self.channels) < initial_length:
            self.save_channels()
            return True
        return False

    def get_channel_config(self, target_channel: str) -> Optional[ChannelConfig]:
        """Get configuration for specific channel"""
        for channel in self.channels:
            if channel.target_channel == target_channel:
                return channel
        return None
