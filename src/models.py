from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass
class ChannelPost:
    channel_title: str
    text: str
    date: datetime
    link: Optional[str] = None
    media_type: Optional[str] = None

@dataclass
class ChannelConfig:
    source_channels: List[str]
    target_channel: str
    mistral_agent_id: str
    channel_theme: str
    post_interval_minutes: int

    @classmethod
    def from_dict(cls, data: dict) -> 'ChannelConfig':
        return cls(
            source_channels=data['source_channels'],
            target_channel=data['target_channel'],
            mistral_agent_id=data.get('mistral_agent_id'),
            channel_theme=data.get('channel_theme', ''),
            post_interval_minutes=int(data['post_interval_minutes'])
        )

    def to_dict(self) -> dict:
        return {
            'source_channels': self.source_channels,
            'target_channel': self.target_channel,
            'mistral_agent_id': self.mistral_agent_id,
            'post_interval_minutes': self.post_interval_minutes
        }
