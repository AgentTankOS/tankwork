import logging
import asyncio
import time
import os
import platform
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator
from .computer_use_providers.computer_use_tank.claude import (
    TankClaudeController, 
    CommandConfig,
    ScalingConfig,
    ScreenshotConfig
)
from .computer_use_interface import BaseComputerUseProvider, ModelProvider, ComputerUseProvider

class TankHandler(BaseComputerUseProvider):
    """Tank implementation for computer control"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Create narrative logger at INFO level
        self.narrative_logger = logging.getLogger('ComputerUse.Tank')
        self.narrative_logger.setLevel(logging.INFO)
        self._model_initialized = False

        # Get model settings from config or use defaults
        model_config = config.get('computer_use', {}).get('model', {})
        self.model = model_config.get('type', 'claude-3-5-sonnet-20241022')
        self.provider = model_config.get('provider', 'anthropic')

        # Get API keys and validate
        api_keys = config.get('api_keys', {})
        self.api_keys = {
            'anthropic': api_keys.get('claude') or api_keys.get('anthropic') or os.getenv('ANTHROPIC_API_KEY'),
            'openai': api_keys.get('openai') or os.getenv('OPENAI_API_KEY')
        }

        # Set primary API key based on provider
        self.api_key = self.api_keys.get(self.provider)
        if not self.api_key:
            raise ValueError(f"API key not found for provider: {self.provider}")

        # UI settings if needed
        self.showui_config = model_config.get('showui', {})
        self.max_pixels = self.showui_config.get('max_pixels', 1344)
        self.awq_4bit = self.showui_config.get('awq_4bit', False)

        # Get display settings
        display_config = config.get('display', {})
        self.display_width = display_config.get('width', 1024)
        self.display_height = display_config.get('height', 768)
        self.display_number = display_config.get('number', 1)

        # Create enhanced config for Tank controller
        self.command_config = CommandConfig(
            verify_steps=False,
            timeout=300,
            response_timeout=30,
            max_retries=3,
            max_tokens=1024,
            temperature=0,
            history_size=10,
            display_width=self.display_width,
            display_height=self.display_height,
            display_number=self.display_number,
            scaling=ScalingConfig(
                enabled=True,
                base_width=1366,
                base_height=768,
                scale_quality=85,
                maintain_aspect_ratio=True
            ),
            screenshot=ScreenshotConfig(
                compression=True,
                quality=85,
                max_dimension=1920,
                format="png",
                optimize=True
            )
        )

        # Setup enhanced system prompt
        base_prompt = f"""You are controlling a desktop application on {platform.system()}.

System Context:
- OS: {platform.system()}
- Python: {platform.python_version()}
- Display: {self.display_width}x{self.display_height}
- Model: {self.model}
- Provider: {self.provider}

"""

        # Initialize controller with enhanced configuration
        self.controller = TankClaudeController(
            api_key=self.api_key,
            model=self.model,
            config=self.command_config,
            system_prompt=base_prompt,
            logger=self.logger
        )

        # Initialize tool statistics
        self.tool_stats = {}

    async def init_session(self):
        """Initialize session"""
        try:
            self.logger.info("Initializing Tank session...")
            await self.controller.init_session()
            self._is_initialized = True
            self._model_initialized = True
            self.logger.info("Tank session initialized successfully")
            return self
            
        except Exception as e:
            self.logger.error(f"Failed to initialize session: {str(e)}")
            raise RuntimeError(f"Session initialization failed: {str(e)}")

    async def close(self):
        """Cleanup resources"""
        try:
            self.logger.info("Closing Tank session...")
            await self.controller.close()
            self._is_initialized = False
            self._model_initialized = False
            self.tool_stats.clear()
            self.logger.info("Tank session closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing session: {str(e)}")

    async def execute_command(self, command: str) -> AsyncGenerator[str, None]:
        """Execute command with full logging and streaming results"""
        start_time = time.time()
        try:
            if not self._is_initialized:
                await self.init_session()

            command = command.strip()
            self.logger.info(f"Processing command: {command}")
            self.logger.debug("Starting command execution")

            seen_messages = set()  # Track unique messages within this command execution
            
            try:
                async for result in self.controller.execute_command(command):
                    # Check for cancellation
                    if asyncio.current_task().cancelled():
                        self.narrative_logger.info("Claude: Command was cancelled.")
                        # Instead of re-raising, just return or break
                        yield "Command cancelled"
                        return
                    
                    # Clean the result
                    cleaned_result = result.strip()
                    if not cleaned_result:
                        continue
                        
                    # Use hash of result and timestamp for uniqueness
                    message_hash = hash(f"{cleaned_result}_{time.time()}")
                    if message_hash in seen_messages:
                        continue
                    seen_messages.add(message_hash)
                    
                    # Log through narrative logger only once
                    self.narrative_logger.info(f"Claude: {cleaned_result}")
                    
                    # Small delay to allow processing
                    await asyncio.sleep(0.1)
                    
                    yield cleaned_result

            except asyncio.CancelledError:
                self.logger.info("Command cancelled, cleaning up...")
                # Do local cleanup, but do NOT re-raise here.
                # self.controller.clear_history()
                # self._is_initialized = False
                self.narrative_logger.info("Claude: Command was cancelled.")
                yield "Command cancelled"
                # Return instead of raise
                return
                
        except asyncio.CancelledError:
            # If this block is reached, just log but don't re-raise
            self.logger.info("Command was cancelled (TankHandler).")
            yield "Command cancelled"
            return
        except Exception as e:
            error_msg = f"Command execution error: {str(e)}"
            self.logger.error(error_msg)
            self.narrative_logger.info(f"Claude: {error_msg}")
            yield error_msg

    async def cancel_current(self) -> None:
        """Cancel current command and reset state"""
        self.logger.info("Cancelling current Tank command")
        try:
            await self.controller.cancel_current()
            # If you do not want to re-init the session here,
            # keep this commented out:
            # self._is_initialized = False
            self.tool_stats.clear()
        except Exception as e:
            self.logger.error(f"Error during cancellation: {str(e)}")
            raise

    async def get_status(self) -> Dict[str, Any]:
        """Get current system status"""
        if not self._is_initialized:
            return {"status": "not_initialized"}
        return await self.controller.get_system_status()
