import asyncio
import sys
import time
from typing import Optional, Tuple
import threading
import signal
import os
import psutil
from PySide6.QtWidgets import QApplication
sys.dont_write_bytecode = True

from config.config import load_config
from config.logging_config import setup_logging
from ui.app import AgentUI
from core.screenshot import ScreenshotHandler
from core.skills.ticker_analysis.screenshot_analyzer import ScreenshotAnalyzer as ImageAnalyzer
from core.computer_use_factory import get_computer_use_handler
from core.narrative_processor import setup_narrative_processor

class ApplicationManager:
    """Manage application lifecycle and resources"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.computer_use_handler = None
        self.loop = None
        self.app = None
        self.qt_app = None
        self.voice_loop = None
        self.voice_thread = None
        self.shutdown_initiated = False
        self.logger.debug("ApplicationManager initialized")

    def setup_voice_event_loop(self):
        """Set up event loop for voice commands"""
        self.logger.debug("Setting up voice command event loop...")
        try:
            # Create event loop in new thread
            self.voice_loop = asyncio.new_event_loop()
            
            def run_voice_loop():
                asyncio.set_event_loop(self.voice_loop)
                self.voice_loop.run_forever()
                
            self.voice_thread = threading.Thread(target=run_voice_loop, daemon=True)
            self.voice_thread.start()
            self.logger.debug("Voice command event loop initialized")
            
        except Exception as e:
            self.logger.error(f"Voice event loop setup error: {str(e)}")

    async def start_computer_use(self) -> bool:
        """Initialize and start computer use handler"""
        try:
            self.logger.debug("Starting computer use initialization")
            
            # Create the computer use handler
            provider = self.config.get('computer_use', {}).get('implementation', 'tank')
            self.computer_use_handler = get_computer_use_handler(self.config)
            
            # Initialize session
            self.logger.debug("Initializing handler session...")
            await self.computer_use_handler.init_session()
            self.logger.debug("Handler session initialized")
            
            return True

        except Exception as e:
            self.logger.error(f"Error starting computer use handler: {str(e)}", exc_info=True)
            return False
            
    async def async_init(self):
        """Initialize all async components"""
        try:
            self.logger.debug("Starting async initialization")

            # Set up voice command event loop first (optional if you use voice)
            self.setup_voice_event_loop()
            
            # Start computer use handler
            self.logger.debug("Initializing computer use...")
            if not await self.start_computer_use():
                raise RuntimeError("Failed to initialize computer use handler")
                
            self.logger.info("Computer use handler started successfully")
            
            # Initialize screenshot pieces (optional for your app)
            screenshot_handler = ScreenshotHandler()
            screenshot_analyzer = ImageAnalyzer(self.config)
            
            # Initialize UI
            self.logger.debug("Initializing UI...")
            self.app = AgentUI(
                config=self.config,
                computer_use_handler=self.computer_use_handler,
                screenshot_handler=screenshot_handler,
                screenshot_analyzer=screenshot_analyzer,
                voice_loop=self.voice_loop,
                on_shutdown=self.handle_ui_shutdown
            )
            
            self.logger.info("Starting application UI...")
            self.app.show()
            
        except Exception as e:
            self.logger.error(f"Async initialization error: {str(e)}", exc_info=True)
            raise

    async def cleanup(self):
        """Clean up application resources"""
        if self.shutdown_initiated:
            return
            
        self.shutdown_initiated = True
        self.logger.info("Starting application cleanup...")

        cleanup_tasks = []

        # Voice cleanup (if used)
        if hasattr(self, 'voice_loop'):
            try:
                self.logger.info("Stopping voice command loop...")
                if self.voice_loop and self.voice_loop.is_running():
                    self.voice_loop.call_soon_threadsafe(self.voice_loop.stop)
                if self.voice_thread and self.voice_thread.is_alive():
                    self.voice_thread.join(timeout=5)
            except Exception as e:
                self.logger.error(f"Error stopping voice loop: {str(e)}")
        
        # Computer use handler cleanup
        if self.computer_use_handler:
            try:
                self.logger.info("Closing computer use handler...")
                await self.computer_use_handler.close()
            except Exception as e:
                self.logger.error(f"Error closing computer use handler: {str(e)}")

        # Cleanup pending tasks
        if self.loop and self.loop.is_running():
            try:
                self.logger.info("Cleaning up pending tasks...")
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    if not task.done():
                        task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            except Exception as e:
                self.logger.error(f"Error cleaning up tasks: {str(e)}")

        self.logger.info("Application cleanup completed")

    def handle_ui_shutdown(self):
        """Handle UI shutdown request"""
        if self.shutdown_initiated:
            return
            
        self.logger.info("UI requested shutdown, initiating cleanup...")
        
        try:
            # Hide UI immediately
            if self.qt_app:
                self.qt_app.quit()
            
            # Clean up server and background tasks
            if self.loop and self.loop.is_running():
                self.loop.run_until_complete(self.cleanup())
                self.loop.stop()
            
            # Exit process
            self.logger.info("Shutdown complete, exiting...")
            os._exit(0)
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")
            os._exit(1)
                
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        if self.shutdown_initiated:
            return
            
        self.logger.info("Shutdown signal received, cleaning up...")
        self.handle_ui_shutdown()
                
    def run(self):
        """Run the application"""
        try:
            self.logger.debug("Starting application run sequence")
            # Initialize Qt Application first
            self.qt_app = QApplication(sys.argv)
            self.logger.debug("Qt Application initialized")
            
            # Setup event loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.logger.debug("Event loop initialized")
            
            # Setup signal handlers
            signal.signal(signal.SIGINT, self.handle_shutdown)
            signal.signal(signal.SIGTERM, self.handle_shutdown)
            self.logger.debug("Signal handlers setup complete")
            
            # Run async initialization
            self.logger.debug("Running async initialization...")
            self.loop.run_until_complete(self.async_init())
            
            # Start Qt event loop
            self.logger.info("Starting Qt event loop")
            return self.qt_app.exec()
            
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received...")
            self.handle_ui_shutdown()
        except Exception as e:
            self.logger.error(f"Application error: {str(e)}", exc_info=True)
            raise
        finally:
            try:
                if self.loop and self.loop.is_running():
                    self.loop.run_until_complete(self.cleanup())
            except Exception as e:
                self.logger.error(f"Error during cleanup: {str(e)}")

def main():
    from config.config import load_config
    from config.logging_config import setup_logging

    # Setup logging
    main_logger, perf_logger = setup_logging()
    main_logger.info("Starting application initialization...")

    try:
        # Load configuration
        config = load_config()
        main_logger.info("Configuration loaded successfully")
        
        # Create and run application manager 
        app_manager = ApplicationManager(config, main_logger)
        sys.exit(app_manager.run())
        
    except Exception as e:
        main_logger.error(f"Startup error: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
