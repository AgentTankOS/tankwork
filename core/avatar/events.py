# core/avatar/events.py

from typing import Protocol, List
from .models import Avatar

class AvatarObserver(Protocol):
    """Protocol for objects that need to respond to avatar changes"""
    def on_avatar_changed(self, avatar: Avatar) -> None:
        """Handle avatar change event"""
        ...

class AvatarEventDispatcher:
    """Handles avatar change event distribution"""
    
    def __init__(self):
        self._observers: List[AvatarObserver] = []
    
    def add_observer(self, observer: AvatarObserver) -> None:
        """Add an observer to be notified of avatar changes"""
        if observer not in self._observers:
            self._observers.append(observer)
    
    def remove_observer(self, observer: AvatarObserver) -> None:
        """Remove an observer"""
        if observer in self._observers:
            self._observers.remove(observer)
    
    def notify_all(self, avatar: Avatar) -> None:
        """Notify all observers of an avatar change"""
        for observer in self._observers:
            try:
                observer.on_avatar_changed(avatar)
            except Exception as e:
                # Log error but continue notifying other observers
                from logging import getLogger
                logger = getLogger('CryptoAnalyzer.AvatarSystem')
                logger.error(f"Error notifying observer {observer}: {str(e)}")