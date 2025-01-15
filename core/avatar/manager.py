# core/avatar/manager.py

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from config.avatar_config import AVATAR_CONFIGS
from .models import Avatar
from .events import AvatarEventDispatcher, AvatarObserver

class AvatarManager:
    """Manages avatar state and configuration"""
    
    def __init__(self):
        self.logger = logging.getLogger('CryptoAnalyzer.AvatarSystem')
        self.event_dispatcher = AvatarEventDispatcher()
        
        # Load avatar configurations
        self._avatars: Dict[str, Avatar] = {}
        self._current_avatar: Optional[Avatar] = None
        
        self._load_avatars()
        self._set_default_avatar()
    
    def _load_avatars(self) -> None:
        """Load all avatar configurations"""
        for avatar_id, config in AVATAR_CONFIGS.items():
            try:
                avatar = Avatar.from_config(avatar_id, config)
                self._avatars[avatar_id] = avatar
            except Exception as e:
                self.logger.error(f"Error loading avatar {avatar_id}: {str(e)}")
    
    def _set_default_avatar(self) -> None:
        """Set the default avatar (first one in config)"""
        if self._avatars:
            default_id = next(iter(self._avatars))
            self.set_current_avatar(default_id)
    
    def set_current_avatar(self, avatar_id: str) -> None:
        """Change the current avatar"""
        if avatar_id not in self._avatars:
            self.logger.error(f"Avatar {avatar_id} not found")
            return
            
        self._current_avatar = self._avatars[avatar_id]
        self.logger.info(f"Avatar changed to: {self._current_avatar.name}")
        
        # Get reference to UI if available
        ui = getattr(self, 'ui', None)
        if ui and hasattr(ui, 'avatar_widget'):
            # Check if avatar has video and if the path exists
            if self._current_avatar.video_path and Path(str(self._current_avatar.video_path)).exists():
                self.logger.info(f"Setting video path: {self._current_avatar.video_path}")
                ui.avatar_widget.start_video(str(self._current_avatar.video_path))
            else:
                self.logger.info(f"Setting image path: {self._current_avatar.image_path}")
                ui.avatar_widget.set_image(str(self._current_avatar.image_path))
        else:
            self.logger.error("No UI reference found for avatar update")
        
        self.event_dispatcher.notify_all(self._current_avatar)
    
    def get_current_avatar(self) -> Optional[Avatar]:
        """Get the current avatar configuration"""
        return self._current_avatar
    
    def get_next_avatar_id(self) -> str:
        """Get the ID of the next avatar in rotation"""
        if not self._current_avatar:
            return next(iter(self._avatars))
            
        avatar_ids = list(self._avatars.keys())
        current_index = avatar_ids.index(self._current_avatar.id)
        next_index = (current_index + 1) % len(avatar_ids)
        return avatar_ids[next_index]
    
    def add_observer(self, observer: AvatarObserver) -> None:
        """Add an observer for avatar changes"""
        self.event_dispatcher.add_observer(observer)
    
    def remove_observer(self, observer: AvatarObserver) -> None:
        """Remove an avatar change observer"""
        self.event_dispatcher.remove_observer(observer)
    
    @property
    def current_voice_id(self) -> Optional[str]:
        """Get current avatar's voice ID"""
        return self._current_avatar.voice_id if self._current_avatar else None
    
    @property
    def current_accent_color(self) -> str:
        """Get current avatar's accent color"""
        return self._current_avatar.accent_color if self._current_avatar else "#ff4a4a"
    
    def get_prompt(self, prompt_type: str) -> str:
        """Get a specific prompt for the current avatar"""
        if not self._current_avatar:
            return ""
        return self._current_avatar.get_prompt(prompt_type)