# core/avatar/models.py

from dataclasses import dataclass
from typing import Dict, Optional, List
from pathlib import Path

@dataclass
class AvatarPrompts:
    """Container for various prompt types"""
    personality: str
    analysis: str
    narrative: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'AvatarPrompts':
        return cls(
            personality=data.get('personality', ''),
            analysis=data.get('analysis', ''),
            narrative=data.get('narrative', '')
        )

@dataclass
class Avatar:
    """Represents a complete avatar configuration"""
    id: str
    name: str
    image_path: Path
    video_path: Optional[Path]
    voice_id: str
    accent_color: str
    prompts: AvatarPrompts
    skills: List[str]  # Add skills field
    
    @classmethod
    def from_config(cls, avatar_id: str, config: Dict) -> 'Avatar':
        return cls(
            id=avatar_id,
            name=config['name'],
            image_path=Path(config['image_path']),
            video_path=Path(config['video_path']) if config.get('video_path') else None,
            voice_id=config['voice_id'],
            accent_color=config['accent_color'],
            prompts=AvatarPrompts.from_dict(config['prompts']),
            skills=config.get('skills', [])  # Get skills with empty list as default
        )
    
    def get_prompt(self, prompt_type: str) -> str:
        """Get a specific prompt type for this avatar"""
        return getattr(self.prompts, prompt_type, '')