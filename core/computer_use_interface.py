from abc import ABC, abstractmethod
import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field

@dataclass
class ComputerUseConfig:
    """Configuration for computer use providers"""
    display_width: int = 1024
    display_height: int = 768
    display_number: int = 1
    scaling_enabled: bool = True
    screenshot_optimization: bool = True
    history_size: int = 10
    max_retries: int = 3
    implementation: str = 'tank'  # Default to tank implementation
    model: Optional[Dict[str, Any]] = None  # Model configuration
    model_provider: Optional[str] = None  # Model provider
    provider: Optional[str] = None  # For backward compatibility
    
    def __post_init__(self):
        # Initialize model as empty dict if None
        if self.model is None:
            self.model = {}

class ModelProvider(Enum):
    """Available model providers"""
    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"
    GPT4 = "gpt4"

    @classmethod
    def from_string(cls, provider: str) -> 'ModelProvider':
        try:
            return cls[provider.upper()]
        except KeyError:
            raise ValueError(f"Unknown model provider: {provider}")

@dataclass
class ComputerUseProvider:
    """Provider configuration"""
    model_provider: Optional[ModelProvider] = None
    
    @classmethod
    def from_string(cls, model_provider: Optional[str] = None) -> 'ComputerUseProvider':
        model = ModelProvider.from_string(model_provider) if model_provider else None
        return cls(model_provider=model)

class BaseComputerUseProvider(ABC):
    """Base class for computer use providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = ComputerUseConfig(**config.get('computer_use', {}))
        self.logger = logging.getLogger(f'ComputerUse.{self.__class__.__name__}')
        self.session: Optional[aiohttp.ClientSession] = None
        self._is_initialized = False
        self._loop = None
        self.tool_stats: Dict[str, Any] = {}
        
    @abstractmethod
    async def init_session(self):
        """Initialize provider session"""
        pass
        
    @abstractmethod
    async def execute_command(self, command: str) -> Optional[str]:
        """Execute a command and return the result"""
        pass
        
    @abstractmethod
    async def close(self):
        """Cleanup resources"""
        pass

    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """Get provider status"""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized
        
    def get_loop(self):
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop