# File: ui/app.py

import sys
import threading
import asyncio
import logging
import time
import platform
import io
from datetime import datetime
from pathlib import Path
from enum import Enum

# Third-party library imports
import cv2
import numpy as np
from PIL import Image

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, 
    QMainWindow, 
    QWidget, 
    QVBoxLayout, 
    QHBoxLayout, 
    QPushButton, 
    QLabel, 
    QTextEdit, 
    QFrame,
    QScrollArea,
    QSizePolicy
)
from PySide6.QtCore import (
    Qt, 
    QTimer, 
    QSize, 
    QPoint, 
    Signal,
    Slot,       
    QRect, 
    QPropertyAnimation, 
    QBuffer, 
    QEasingCurve,
    QObject
)
from PySide6.QtGui import (
    QColor, 
    QPainter, 
    QBrush, 
    QPen, 
    QLinearGradient, 
    QFont, 
    QPainterPath, 
    QImage, 
    QPixmap,
    QTextCursor
)

# Local application imports
from core.skills.ticker_analysis.token_analyzer import CryptoAnalyzer
from core.voice import VoiceHandler
from core.screenshot import ScreenshotHandler
from core.narrative_processor import setup_narrative_processor
from .notification import NotificationWindow
from core.avatar.manager import AvatarManager
from core.voice_commands import VoiceCommandButton, VoiceCommandHandler
from core.command_accelerator.general_command_accelerator import GeneralCommandAccelerator
from .loading_eyes import LoadingEyesWidget

# IMPORTANT for new system
from core.command_manager import AsyncCommandManager, CommandContext as CMContext, CommandState as CMState
from core.computer_use_factory import get_computer_use_handler

# Constants
WINDOW_WIDTH = 300
WINDOW_HEIGHT = 352
INPUT_HEIGHT = 80

# Rename the local UI-specific command states to avoid confusion with CMState
class UICommandState(Enum):
    READY = 1
    RUNNING = 2

def get_display_scaling():
    """Get display scaling factor safely"""
    try:
        if platform.system() == "Darwin":  # macOS
            from AppKit import NSScreen
            return NSScreen.mainScreen().backingScaleFactor()
        return 1.0
    except:
        return 1.0

class UICommandSignalBus(QObject):
    """A signal bus so we can emit UI updates on the main thread."""
    commandUpdated = Signal(object)  # We'll pass the CommandContext

class CommandInputWidget(QTextEdit):
    """Widget for command input"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Define constant height
        self.FIXED_HEIGHT = 80
        
        self.setStyleSheet("""
            QTextEdit {
                border: none;
                background-color: rgba(240, 240, 240, 0.5);  /* Light gray background */
                color: #000000;
                font-size: 13px;
                border-top: 1px solid rgba(0,0,0,0.1);
                padding: 0px 8px 8px 8px;
                min-height: 80px;
            }
        """)
        self.setPlaceholderText("Type your command...")
        self.setFixedHeight(self.FIXED_HEIGHT)
        self.setMinimumHeight(self.FIXED_HEIGHT)  # Ensure minimum height is set

    # Add the new method here, at the same indentation level as __init__
    def keyPressEvent(self, event):
        """Handle key press events"""
        # Check if Enter was pressed without Shift
        if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
            event.accept()  # Accept the event to prevent default handling
            
            # Find the parent AgentUI instance and call _handle_command
            parent = self.parent()
            while parent is not None:
                if isinstance(parent, AgentUI):
                    parent._handle_command()
                    return
                parent = parent.parent()
        else:
            # For all other keys, use default handling
            super().keyPressEvent(event)

class ChatBubble(QFrame):
    def __init__(self, text, sender_type="assistant", parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        # Try smaller margins/spacings:
        layout.setContentsMargins(0, 0, 0, 0)  
        layout.setSpacing(0)
        self.setLayout(layout)

        self.setFrameShape(QFrame.NoFrame)
        self.setFrameShadow(QFrame.Plain)

        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.adjustSize()
        # Make sure label padding is small:
        self.label.setStyleSheet("""
            QLabel {
                color: #000000;
                font-size: 13px;
                padding: 0px;
            }
        """)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        if sender_type == "user":
            self.setStyleSheet("""
                QFrame {
                    background-color: #000000;
                    border-radius: 8px;
                    padding: 0px 4px 4px 4px;
                    margin: 8px 4px 0px 8px;
                }
            """)
            self.label.setStyleSheet("""
                QLabel {
                    color: #ffffff;
                    font-size: 13px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #f5f5f5;
                    border: 1px solid #f5f5f5;
                    border-radius: 8px;
                    padding: 4px;
                    margin: 0px 0px 0px 8px;
                }
            """)
            self.label.setStyleSheet("""
                QLabel {
                    color: #000000;
                    font-size: 13px;
                    padding: 0px;
                }
            """)

        layout.addWidget(self.label)
        self.label.adjustSize()

class ChatLogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Set this widget to collapse to content size
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)  # Reset to zero
        self.layout.setSpacing(8)  # Space between bubbles
        self.setLayout(self.layout)

    def add_bubble(self, text, sender_type="assistant"):
        bubble = ChatBubble(text, sender_type=sender_type)
        
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)  # Make container collapse too
        
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)  # Match input container margins
        container_layout.setSpacing(0)
        
        if sender_type == "user":
            container_layout.addStretch()
            container_layout.addWidget(bubble, 0, Qt.AlignRight)
            self.layout.addWidget(container)
        else:
            container_layout.addWidget(bubble, 0, Qt.AlignLeft)
            container_layout.addStretch()
            self.layout.addWidget(container)

        # Update sizes after adding content
        container.adjustSize()
        self.adjustSize()
        
        # Auto-scroll
        scroll_area = self._get_scroll_area_parent()
        if scroll_area is not None:
            scroll_area.widget().adjustSize()
            # Limit scroll area height to 200
            content_height = self.sizeHint().height()
            scroll_area.setFixedHeight(min(content_height, 200))
            scroll_area.verticalScrollBar().setValue(
                scroll_area.verticalScrollBar().maximum()
            )

    def _get_scroll_area_parent(self):
        p = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p
            p = p.parent()
        return None



class ModernButton(QPushButton):
    """Custom button with hover/click animations"""
    def __init__(self, text, parent=None, accent_color=QColor("#ff4a4a"), icon=None):
        super().__init__(text, parent)
        self.accent_color = accent_color
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)
        if icon:
            self.setIcon(icon)

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent_color.name()};
                border-radius: 14px;
                color: white;
                font-size: 14px;
                padding: 1px 10px;
                border: none;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {QColor(accent_color.lighter(110)).name()};
            }}
            QPushButton:pressed {{
                background-color: {QColor(accent_color.darker(110)).name()};
            }}
        """)

class HoverCursorButton(QPushButton):
    """Forces Qt.PointingHandCursor on hover"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_Hover, True)

    def enterEvent(self, event):
        self.setCursor(Qt.PointingHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)

class CircularAvatarWidget(QWidget):
    """Circular video/image widget"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update)
        self.cap = None
        self.static_image = None
        self.is_video = False
        
        # Add loading eyes
        self.loading_eyes = LoadingEyesWidget(self)

    def get_resize_dimensions(self, frame_width, frame_height, target_width, target_height):
        """Calculate dimensions that maintain aspect ratio while filling the target area"""
        frame_aspect = frame_width / frame_height
        target_aspect = target_width / target_height
        
        if frame_aspect > target_aspect:
            # Frame is wider than target: fit to height
            new_height = target_height
            new_width = int(target_height * frame_aspect)
            x_offset = (new_width - target_width) // 2
            y_offset = 0
        else:
            # Frame is taller than target: fit to width
            new_width = target_width
            new_height = int(target_width / frame_aspect)
            x_offset = 0
            y_offset = (new_height - target_height) // 2
            
        return new_width, new_height, x_offset, y_offset

    def set_image(self, image_path):
        """Set static image avatar"""
        self.stop_video()
        self.is_video = False
        self.static_image = QImage(image_path)
        self.update()

    def start_video(self, video_path):
        """Start video avatar"""
        self.logger = logging.getLogger('CryptoAnalyzer.UI')  # Add this
        
        if Path(video_path).exists():
            self.logger.info(f"Starting video from: {video_path}")
            self.static_image = None
            self.is_video = True
            self.cap = cv2.VideoCapture(str(video_path))
            if not self.cap.isOpened():
                self.logger.error(f"Failed to open video file: {video_path}")
                return
            self.video_timer.start(100)
        else:
            self.logger.error(f"Video file not found: {video_path}")

    def stop_video(self):
        """Stop video playback"""
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_timer.stop()

    def set_loading(self, is_loading: bool):
        """Toggle loading state"""
        self.loading_eyes.set_loading(is_loading)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.loading_eyes.update_positions()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.addEllipse(self.rect())
        painter.setClipPath(path)

        if self.is_video and self.cap:
            ret, frame = self.cap.read()
            if ret:
                # Loop if at end
                if self.cap.get(cv2.CAP_PROP_POS_FRAMES) == self.cap.get(cv2.CAP_PROP_FRAME_COUNT):
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                
                # Get frame dimensions that preserve aspect ratio
                frame_h, frame_w = frame.shape[:2]
                new_w, new_h, x_off, y_off = self.get_resize_dimensions(
                    frame_w, frame_h, 
                    self.width(), self.height()
                )
                
                # Resize frame maintaining aspect ratio
                frame = cv2.resize(frame, (new_w, new_h))
                
                # Crop to target size
                frame = frame[y_off:y_off+self.height(), x_off:x_off+self.width()]
                
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = QImage(frame.data, frame.shape[1], frame.shape[0],
                             frame.strides[0], QImage.Format_RGB888)
                painter.drawImage(self.rect(), image)
                
        elif self.static_image:
            scaled = self.static_image.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.drawImage(self.rect(), scaled)

        # Draw border
        pen = QPen()
        pen.setWidth(2)
        accent_color = QColor(self.parent().accent_color) if hasattr(self.parent(), 'accent_color') else QColor("#ff4a4a")
        pen.setColor(QColor(accent_color.name() + "20"))
        painter.setPen(pen)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

class AgentUI(QMainWindow):
    """Main application window"""

    # ADD A LOG SIGNAL HERE:
    logMessageSignal = Signal(dict)
    
    def __init__(
        self, 
        config, 
        on_shutdown=None, 
        screenshot_handler=None, 
        screenshot_analyzer=None, 
        computer_use_handler=None,
        narrative_processor=None,
        voice_loop=None 
    ):
        super().__init__()

        self.is_muted = False

        # Store the initial geometry so we can always expand the same amount
        self._original_geometry = None

        # Setup managers
        self.avatar_manager = AvatarManager()
        self.avatar_manager._load_avatars()

        self.voice_loop = voice_loop
        self.logger = logging.getLogger('CryptoAnalyzer.UI')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.on_shutdown = on_shutdown
        self.config = config
        
        initial_avatar = next(iter(self.avatar_manager._avatars.values()))
        self.accent_color = initial_avatar.accent_color if initial_avatar else "#ff4a4a"

        # Initialize core features
        self.voice_handler = VoiceHandler(config, self.avatar_manager)
        self.crypto_analyzer = CryptoAnalyzer(config)
        self.screenshot_handler = screenshot_handler or ScreenshotHandler()
        self.screenshot_analyzer = screenshot_analyzer
        provider = config.get('computer_use', {}).get('implementation', 'tank')
        self.computer_use = computer_use_handler or get_computer_use_handler(provider, config)

        # Observe changes
        self.avatar_manager.add_observer(self.voice_handler)
        self.avatar_manager.add_observer(self.crypto_analyzer)

        self.command_accelerator = GeneralCommandAccelerator(config)

        # Setup event loop
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        # Create the command manager
        self.command_manager = AsyncCommandManager(handler=self.computer_use, config=config)

        # Initialize notification window
        self.notification = NotificationWindow(parent=self)

        # Possibly create the narrative processor
        if narrative_processor:
            self.logger.info("Using provided narrative processor")
            self.narrative_processor = narrative_processor
        else:
            self.logger.info("Setting up new narrative processor...")
            self.avatar_manager.ui = self
            self.narrative_processor = setup_narrative_processor(
                config=config,
                avatar_manager=self.avatar_manager,
                voice_handler=self.voice_handler,
                voice_loop=self.voice_loop
            )
            self.narrative_processor.log_signal = self.logMessageSignal 
            self.avatar_manager.add_observer(self.narrative_processor)

            # Start the queue in the voice_loop
            if self.voice_loop and self.voice_loop.is_running():
                self.logger.info("Starting narrative processor in voice loop...")
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.command_manager.process_queue(),
                        self.voice_loop
                    )
                    try:
                        fut.result(timeout=5)
                    except asyncio.TimeoutError:
                        self.logger.warning("Command queue did not confirm within 5s.")
                    self.logger.info("Command manager queue started.")
                except Exception as e:
                    self.logger.error(f"Failed to start command queue: {e}", exc_info=True)
            else:
                self.logger.error("No running voice_loop for narrative processor.")

        self.command_active = False
        self.command_state = UICommandState.READY
        self._drag_pos = None

        self.voice_command_handler = VoiceCommandHandler(config)

        # Create a signal bus for background->main updates
        self.command_signal_bus = UICommandSignalBus()
        self.command_signal_bus.commandUpdated.connect(self._on_command_update_main_thread)

        # Connect logMessageSignal -> a slot to update logs on main thread
        self.logMessageSignal.connect(self._on_new_log_message)

        # Start manager queue if no voice_loop or if fallback
        if self.voice_loop and self.voice_loop.is_running():
            self.logger.info("Starting command manager on voice_loop...")
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self.command_manager.process_queue(),
                    self.voice_loop
                )
                fut.result(timeout=1)
                self.logger.info("Command manager queue started (voice_loop).")
            except Exception as e:
                self.logger.error(f"Failed to start manager queue: {e}")
        else:
            if self.loop and self.loop.is_running():
                self.logger.info("Starting command manager on self.loop (no voice_loop).")
                asyncio.run_coroutine_threadsafe(self.command_manager.process_queue(), self.loop)
            else:
                self.logger.error("No running loop for commands; won't process!")

        # Initialize UI first
        self.init_ui()

        # Now set up the avatar after UI is initialized
        if initial_avatar:
            self.name_label.setText(initial_avatar.name)
            self._update_accent_colors(initial_avatar.accent_color)
            self.avatar_manager.ui = self
            self.avatar_manager._set_default_avatar()

        # Connect GPT classification signal
        self.voice_command_handler.classificationComplete.connect(
            self._handle_classification_with_original
        )

    # ------------------- NEW SLOT FOR LOG MESSAGES -------------------
    @Slot(dict)
    def _on_new_log_message(self, new_log: dict):
        """
        Called on the main/UI thread whenever self.logMessageSignal.emit(...) 
        is triggered from a background thread. We now add a chat bubble.
        """
        self._append_chat_bubble(new_log)

    # ----------------------------------------------------------------

    def update_server_status(self, is_healthy: bool):
        pass

    def cleanup(self):
        self.logger.info("Starting UI cleanup...")

        if hasattr(self, 'avatar_widget'):
            try:
                self.avatar_widget.stop_video()
            except Exception as e:
                self.logger.error(f"Error stopping avatar video: {str(e)}")

        self.hide()
        
        if hasattr(self, 'avatar_manager'):
            self.avatar_manager.remove_observer(self.voice_handler)
            self.avatar_manager.remove_observer(self.crypto_analyzer)
            self.avatar_manager.remove_observer(self.narrative_processor)
        
        cleanup_loop = asyncio.new_event_loop()
        def cleanup_background():
            try:
                asyncio.set_event_loop(cleanup_loop)
                
                # Cleanup voice command handler
                if hasattr(self, 'voice_command_handler') and self.voice_loop and self.voice_loop.is_running():
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            self.voice_command_handler.close(),
                            self.voice_loop
                        )
                        fut.result(timeout=2)
                    except Exception as e:
                        self.logger.error(f"Error cleaning voice cmd handler: {str(e)}")

                # Cleanup voice handler
                if hasattr(self, 'voice_handler'):
                    try:
                        self.voice_handler.cleanup()
                    except Exception as e:
                        self.logger.error(f"Error cleaning voice handler: {str(e)}")

                # Cleanup computer use
                if self.computer_use and self.loop and self.loop.is_running():
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            self.computer_use.close(),
                            self.loop
                        )
                        fut.result(timeout=10)
                    except Exception as e:
                        self.logger.error(f"Error closing computer use: {str(e)}")

                # Cleanup crypto analyzer
                if hasattr(self, 'crypto_analyzer') and self.loop and self.loop.is_running():
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            self.crypto_analyzer.close(),
                            self.loop
                        )
                        fut.result(timeout=2)
                    except Exception as e:
                        self.logger.error(f"Error closing crypto analyzer: {str(e)}")
                        
                # Cleanup local server (if any)
                if (hasattr(self, 'computer_use') and 
                    hasattr(self.computer_use, 'server_process') and 
                    self.computer_use.server_process):
                    try:
                        self.computer_use.server_process.kill()
                        self.computer_use.server_process.wait(timeout=2)
                    except Exception as e:
                        self.logger.error(f"Error in final server kill: {str(e)}")
            except Exception as e:
                self.logger.error(f"Error in background cleanup: {str(e)}")
            finally:
                cleanup_loop.close()
                
        cleanup_thread = threading.Thread(target=cleanup_background, daemon=True)
        cleanup_thread.start()
        cleanup_thread.join(timeout=0.5)
                
        self.logger.info("UI cleanup completed")

    def closeEvent(self, event):
        self.logger.info("Close event received")
        self.cleanup_and_close()
        event.accept()

    def cleanup_and_close(self):
        try:
            self.logger.info("Starting cleanup process")
            self.cleanup()
            
            if self.on_shutdown:
                self.logger.info("Triggering application shutdown")
                self.on_shutdown()
            else:
                self.logger.warning("No shutdown handler available")
                self.close()
                
        except Exception as e:
            self.logger.error(f"Error during cleanup/close: {str(e)}")
            self.close()

    def _get_icons(self):
        return {
            'close': "✕",
            'send': "➚"
        }

    def _handle_key_press(self, event):
        if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
            event.accept()
            self._handle_command()
        else:
            QTextEdit.keyPressEvent(self.command_input, event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)

    def _update_accent_colors(self, color: str):
        self.accent_color = color
        button_style = f"""
            QPushButton {{
                background-color: {color};
                border-radius: 14px;
                color: white;
                font-size: 10px;
                padding: 1px 10px;
                border: none;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {QColor(color).lighter(110).name()};
            }}
            QPushButton:pressed {{
                background-color: {QColor(color).darker(110).name()};
            }}
        """
        # Update accent colors for all buttons
        self.region_button.accent_color = QColor(color)
        self.skills_button.accent_color = QColor(color)
        self.fullscreen_button.accent_color = QColor(color)
        self.voice_button.accent_color = QColor(color)
        self.voice_button._setup_styling()
        self.avatar_widget.loading_eyes.update_accent_color(QColor(color))
        
        # Apply styles
        self.region_button.setStyleSheet(button_style)
        self.fullscreen_button.setStyleSheet(button_style)
        self.skills_button.setStyleSheet(button_style)
        
        # Update randomize button border color
        self.randomize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {color};
                border-radius: 16px;
                color: #ffffff;
                font-size: 26px;
                text-align: center;
                line-height: 32px;
                padding: 0 0 5px 3px;
                margin: 0;
            }}
            QPushButton:hover {{
                background-color: {QColor(color).lighter(110).name()};
            }}
        """)

        self.send_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #000000;
                border-radius: 8px;
                color: {color};
                font-size: 20px;
                border: none;
                padding: 0;
                margin: 0;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: #111111;
            }}
        """)

        self.avatar_widget.update()

    def init_ui(self):
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        icons = self._get_icons()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_frame = QFrame()
        self.main_frame.setStyleSheet("""
            QFrame {
                background-color: #0A0A0A;
                border: 1px solid rgba(75, 75, 75, 0.3);
                border-radius: 12px;
            }
        """)
        frame_layout = QVBoxLayout(self.main_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet("""
            QWidget {
                background-color: #000000;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                border-bottom: 1px solid rgba(75, 75, 75, 0.3);
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(4)

        randomize_btn = QPushButton("⟳")
        randomize_btn.setFixedSize(32, 32)
        randomize_btn.setCursor(Qt.PointingHandCursor)
        self.randomize_btn = randomize_btn
        randomize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {self.accent_color};
                border-radius: 16px;
                color: #ffffff;
                font-size: 26px;
                text-align: center;
                line-height: 32px;
                padding: 0 0 5px 3px;
                margin: 0;
            }}
            QPushButton:hover {{
                background-color: {QColor(self.accent_color).name() + "1A"};
            }}
        """)
        randomize_btn.clicked.connect(self.randomize_avatar)

        self.name_label = QLabel("Gennifer")
        self.name_label.setStyleSheet("""
            color: #e0e0e0;
            font-size: 13px;
            font-weight: 500;
            margin-left: 2px;
            border: none;
        """)

        button_size = 32

        self.close_btn = HoverCursorButton(icons['close'])
        self.close_btn.setFixedSize(button_size, button_size)
        self.close_btn.clicked.connect(self.cleanup_and_close)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border-radius: 8px;
                color: #666666;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #ff4a4a;
                color: white;
            }
        """)

        header_layout.addWidget(randomize_btn)
        header_layout.addWidget(self.name_label)
        header_layout.addStretch()

        # Add mute button
        self.mute_btn = HoverCursorButton("🔊")
        self.mute_btn.setFixedSize(button_size, button_size)
        self.mute_btn.clicked.connect(self._toggle_mute)
        self.mute_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border-radius: 8px;
                color: #666666;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #ff4a4a;
                color: white;
            }
        """)

        header_layout.addWidget(self.mute_btn)
        header_layout.addWidget(self.close_btn)

        # Content container
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Avatar container
        avatar_container = QWidget()
        avatar_container.setFixedHeight(156)
        avatar_layout = QVBoxLayout(avatar_container)
        avatar_layout.setContentsMargins(0, 8, 0, 0)
        avatar_layout.setSpacing(0)

        self.avatar_widget = CircularAvatarWidget(self)
        self.avatar_widget.setFixedSize(140, 140)
        avatar_layout.addWidget(self.avatar_widget, alignment=Qt.AlignCenter)

        # Region Buttons
        region_container = QWidget()
        region_layout = QHBoxLayout(region_container)
        region_layout.setContentsMargins(16, 8, 16, 0)
        region_layout.setSpacing(8)

        self.region_button = ModernButton("🗁 Region", accent_color=QColor("#ff4a4a"))
        self.region_button.clicked.connect(self._take_region_screenshot)
        self.region_button.setFixedWidth(110)
        
        self.fullscreen_button = ModernButton("⛶ Full", accent_color=QColor("#ff4a4a"))
        self.fullscreen_button.clicked.connect(self._take_fullscreen_screenshot)
        self.fullscreen_button.setFixedWidth(110)

        region_layout.addWidget(self.region_button)

        # Add the new star button in the middle
        self.skills_button = ModernButton("⭐", accent_color=QColor(self.accent_color))
        self.skills_button.setFixedWidth(40)  # Make it compact
        self.skills_button.clicked.connect(self._toggle_skills_menu)
        region_layout.addWidget(self.skills_button)

        region_layout.addWidget(self.fullscreen_button)

        # Initialize the skills menu
        self._setup_skills_menu()

        # Input container
        input_container = QWidget()
        input_container.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border-radius: 12px;
                margin: 8px 16px 16px 12px;
                padding: 8px 4px 4px 4px;
                
            }
        """)
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(12, 0, 12, 12)
        input_layout.setSpacing(0)


        # After setting up your UI, store the *initial* geometry
        # so we know exactly how high to grow later.
        QTimer.singleShot(0, self._store_initial_geometry)

        # NEW: Scroll area + ChatLogWidget replaces the old self.log_view
        self.chat_scroll_area = QScrollArea()
        self.chat_scroll_area.setWidgetResizable(True)
        self.chat_scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;;
                border: none;
                padding: 0px;
                margin: 8px 0px 0px 0px;
            }
        """)
        self.chat_scroll_area.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.chat_scroll_area.setMaximumHeight(200)  # Set maximum height
        self.chat_scroll_area.setFixedHeight(0)  # Start collapsed
        self.chat_scroll_area.hide()

        # Create the ChatLogWidget and set it as the scroll area's widget
        self.chat_log_widget = ChatLogWidget()  # Add this line
        self.chat_scroll_area.setWidget(self.chat_log_widget)

        # Create input widget
        self.command_input = CommandInputWidget()

        input_overlay = QWidget()
        input_overlay.setStyleSheet("background: transparent;")
        overlay_layout = QHBoxLayout(input_overlay)
        overlay_layout.setContentsMargins(0, 0, 12, 12)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch()

        default_accent = "#ff4a4a"
        try:
            button_accent = self.accent_color if hasattr(self, 'accent_color') else default_accent
            self.voice_button = VoiceCommandButton(accent_color=QColor(button_accent))
        except:
            self.voice_button = VoiceCommandButton(accent_color=QColor(default_accent))

        self.voice_button.clicked.connect(self._toggle_voice_command)
        self.voice_button.recordingStarted.connect(self._start_voice_recording)
        self.voice_button.recordingStopped.connect(self._stop_voice_recording)
        self.voice_button.transcriptionComplete.connect(self._handle_transcription)
        self.voice_command_handler.set_voice_button(self.voice_button)

        self.send_button = HoverCursorButton(self._get_icons()['send'])
        self.send_button.setFixedSize(36, 36)
        self.send_button.clicked.connect(self._handle_command)
        self.send_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #000000;
                border-radius: 8px;
                color: {self.accent_color};
                font-size: 20px;
                border: none;
                padding: 0;
                margin: 0;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: #111111;
            }}
        """)

        overlay_layout.addWidget(self.voice_button, alignment=Qt.AlignRight | Qt.AlignBottom)
        overlay_layout.addWidget(self.send_button, alignment=Qt.AlignRight | Qt.AlignBottom)

        # Add new chat area + input to layout
        input_layout.addWidget(self.chat_scroll_area)
        input_layout.addWidget(self.command_input)
        input_layout.addWidget(input_overlay)

        # Add everything to content layout
        content_layout.addWidget(avatar_container)
        content_layout.addWidget(region_container)
        content_layout.addWidget(input_container)

        frame_layout.addWidget(header)
        frame_layout.addWidget(content_container)
        main_layout.addWidget(self.main_frame)

    def _on_command_update(self, ctx: CMContext):
        """Called by manager from a background thread -> forward to main thread."""
        self.logger.debug(f"_on_command_update() from background: {ctx.state}")
        self.command_signal_bus.commandUpdated.emit(ctx)

    def _store_initial_geometry(self):
        """
        Called once right after the UI is shown for the first time
        so that we lock in the 'small' geometry for future expansions.
        """
        self._original_geometry = self.geometry()

    @Slot(object)
    def _handle_command(self):
        if self.command_state == UICommandState.READY:
            self._send_command()
        else:
            self.logger.info("Cancel button clicked. Cancelling command...")
            self._cancel_command()

    def _cancel_command(self):
        # same code as posted
        if self.voice_loop and self.voice_loop.is_running():
            self.logger.info("Cancelling via command manager on voice_loop...")
            try:
                if hasattr(self, 'voice_handler'):
                    self.voice_handler.cancel_all()
                if hasattr(self, 'narrative_processor'):
                    self.narrative_processor.cancel()
                asyncio.run_coroutine_threadsafe(
                    self.command_manager.cancel_current(),
                    self.voice_loop
                )
            except Exception as e:
                self.logger.error(f"Cancel error: {e}")
                self.avatar_widget.set_loading(False)
                self._reset_command_ui()
        else:
            if self.loop and self.loop.is_running():
                self.logger.info("Cancelling via self.loop...")
                try:
                    if hasattr(self, 'voice_handler'):
                        self.voice_handler.cancel_all()
                    if hasattr(self, 'narrative_processor'):
                        self.narrative_processor.cancel()
                    asyncio.run_coroutine_threadsafe(
                        self.command_manager.cancel_current(),
                        self.loop
                    )
                except Exception as e:
                    self.logger.error(f"Cancel error: {e}")
                    self.avatar_widget.set_loading(False)
                    self._reset_command_ui()
            else:
                self.logger.error("No running event loop to cancel command.")
                self.avatar_widget.set_loading(False)
                self._reset_command_ui()

    def _setup_skills_menu(self):
        """Setup the skills popup menu"""
        self.skills_menu = QWidget(self)
        self.skills_menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.skills_menu.setAttribute(Qt.WA_NoSystemBackground, False)
        self.skills_menu.setAttribute(Qt.WA_TranslucentBackground, False)

        main_layout = QVBoxLayout(self.skills_menu)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header section
        header = QWidget()
        header.setFixedHeight(32)  # Smaller than main window header
        header.setStyleSheet("""
            QWidget {
                background-color: #000000;
                border: none;
                border-radius: 12px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(4)

        # Title in header
        title_label = QLabel("Skills")
        title_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 13px;
                border: none;
                padding: 2px;
            }
        """)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Content section
        content_widget = QWidget()
        content_widget.setStyleSheet("""
            QWidget {
                background-color: #0A0A0A;
                border: none;
                border-radius: 12px;
            }
            QLabel {
                color: white;
                background: none;
                font-size: 13px;
                padding: 2px;
                border: none;
            }
        """)
        
        skills_layout = QVBoxLayout(content_widget)
        skills_layout.setContentsMargins(12, 12, 12, 12)
        skills_layout.setSpacing(8)

        # Get current avatar's skills
        current_avatar = self.avatar_manager.get_current_avatar()
        skills = current_avatar.skills if current_avatar else []

        # If no skills, show a message
        if not skills:
            skill_label = QLabel("No skills available")
            skill_label.setStyleSheet("""
                QLabel {
                    color: #666666;
                    font-size: 13px;
                    padding: 4px;
                }
            """)
            skills_layout.addWidget(skill_label)
        else:
            # Add each skill
            for skill in skills:
                skill_label = QLabel(f"{skill}")
                skill_label.setStyleSheet("""
                    QLabel {
                        color: white;
                        font-size: 13px;
                        padding: 4px;
                    }
                """)
                skills_layout.addWidget(skill_label)

        # Add the sections to main layout
        main_layout.addWidget(header)
        main_layout.addWidget(content_widget)

        # Add border to the entire menu
        self.skills_menu.setStyleSheet("""
            QWidget {
                background-color: #0A0A0A;
                border: 1px solid rgba(75, 75, 75, 0.3);
                border-radius: 12px;
            }
        """)

    def _toggle_skills_menu(self):
        """Show/hide the skills menu"""
        if self.skills_menu.isVisible():
            self.skills_menu.hide()
        else:
            # Update size hint before calculating position
            self.skills_menu.adjustSize()
            
            # Get skills button position and dimensions
            button_pos = self.skills_button.mapToGlobal(QPoint(0, 0))
            button_width = self.skills_button.width()
            button_height = self.skills_button.height()
            menu_width = self.skills_menu.sizeHint().width()
            menu_height = self.skills_menu.sizeHint().height()
            
            # Center horizontally relative to button
            menu_x = button_pos.x() + (button_width - menu_width) // 2
            
            # Position above button with fixed gap
            menu_y = button_pos.y() - menu_height - 8  # 8px gap
            
            self.skills_menu.move(menu_x, menu_y)
            self.skills_menu.show()

    def randomize_avatar(self):
        next_id = self.avatar_manager.get_next_avatar_id()
        self.avatar_manager.set_current_avatar(next_id)
        avatar = self.avatar_manager.get_current_avatar()
        self.name_label.setText(avatar.name)
        self._update_accent_colors(avatar.accent_color)
        self._setup_skills_menu()  # Refresh skills menu for new avatar

    def _send_command(self):
        if self.command_active:
            return

        command = self.command_input.toPlainText().strip()
        if not command:
            return
        
        # Resume narrative processor if it was cancelled
        if hasattr(self, 'narrative_processor'):
            self.narrative_processor.resume()
        if hasattr(self, 'voice_handler'):
            self.voice_handler.uncancel()
        
        # 1) Immediately show the user's bubble
        self._append_chat_bubble({'type': 'command', 'content': command})
        self.command_input.clear()

        # 2) If we've never expanded before, just ensure minimum width
        if not hasattr(self, 'ui_expanded'):
            # Set minimum width to ensure proper word wrapping
            self.chat_log_widget.setMinimumWidth(200)
            
            # Animate window expansion
            if self._original_geometry is not None:
                cur_rect = self.geometry()
                orig_rect = self._original_geometry
                new_h = int(orig_rect.height() * 1.5)

                self.resize_animation = QPropertyAnimation(self, b"geometry")
                self.resize_animation.setDuration(300)
                self.resize_animation.setEasingCurve(QEasingCurve.OutQuad)

                new_rect = QRect(
                    cur_rect.x(),
                    cur_rect.y(), 
                    cur_rect.width(),
                    new_h
                )
                self.resize_animation.setStartValue(cur_rect)
                self.resize_animation.setEndValue(new_rect)
                self.resize_animation.start()

            # Mark the UI as expanded
            self.ui_expanded = True

        # 3) Proceed with command processing
        self.avatar_widget.set_loading(True)
        self.command_active = True
        self.command_state = UICommandState.RUNNING
        self.send_button.setText(self._get_icons()['close'])
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #ff4a4a;
                border-radius: 8px;
                color: #000000;
                font-size: 18px;
                border: none;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background-color: #ff6b6b;
            }
        """)

        async def add_cmd():
            enhanced_command = await self.command_accelerator.enhance_command(command)
            final_command = enhanced_command or command
            await self.command_manager.add_command(
                final_command,
                callback=self._on_command_update
            )

        if self.voice_loop and self.voice_loop.is_running():
            asyncio.run_coroutine_threadsafe(add_cmd(), self.voice_loop)
        else:
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(add_cmd(), self.loop)
            else:
                self.logger.error("No running event loop to process commands.")

    @Slot(object)
    def _on_command_update_main_thread(self, ctx: CMContext):
        """Handle command updates on UI thread"""
        # First check if UI is initialized and context has a result
        if not hasattr(self, 'ui_expanded'):
            return
            
        if ctx.state == CMState.COMPLETED:
            self.logger.info("Command COMPLETED.")
            if ctx.result:  # Only process result if it exists
                # Handle any result-specific logic here
                pass
            self.avatar_widget.set_loading(False)
            self._reset_command_ui()
            self.command_input.clear()

        elif ctx.state == CMState.CANCELLED:
            self.logger.info("Command CANCELLED.")
            self.avatar_widget.set_loading(False)
            self._reset_command_ui()

        elif ctx.state == CMState.FAILED:
            self.logger.info(f"Command FAILED: {ctx.error}")
            self.avatar_widget.set_loading(False)
            self._reset_command_ui()
            if ctx.error:
                self._append_chat_bubble({
                    'type': 'response',
                    'content': f"Command execution error: {ctx.error}"
                })

    ##################################################################
    # We append chat bubbles for command action logs:
    ##################################################################
    def _append_chat_bubble(self, log: dict):
        """
        log: {'type': 'command' or 'response', 'content': '...'}
        """
        if log['type'] == 'command':
            # "command" means user bubble
            self.chat_log_widget.add_bubble(log['content'], sender_type="user")
        else:
            # "response" means assistant bubble
            text = log['content']
            if "Tool Use:" in text:
                # optional: do some formatting
                parts = text.split("Tool Use:")
                formatted = parts[0]
                if len(parts) > 1:
                    formatted += f"\nTool Use:{parts[1]}"
                text = formatted
            self.chat_log_widget.add_bubble(text, sender_type="assistant")
        
        # After adding any bubble, ensure scroll area is properly sized
        self.chat_scroll_area.show()
        
        # Force complete layout update 
        self.chat_log_widget.adjustSize()
        self.chat_scroll_area.adjustSize()
        self.chat_scroll_area.updateGeometry()
        QApplication.processEvents()
        
        # Get actual height needed
        container_height = sum(self.chat_log_widget.layout.itemAt(i).widget().sizeHint().height() 
                            for i in range(self.chat_log_widget.layout.count()))
        scroll_height = min(container_height + 20, 200)  # Add buffer but respect max height
        
        # Update scroll area height
        self.chat_scroll_area.setFixedHeight(scroll_height)
        
        # Add delayed scroll to bottom
        QTimer.singleShot(50, lambda: self.chat_scroll_area.verticalScrollBar().setValue(
            self.chat_scroll_area.verticalScrollBar().maximum()
        ))

    def _reset_command_ui(self):
        self.command_active = False
        self.command_state = UICommandState.READY
        
        # Reset send button
        self.send_button.setText(self._get_icons()['send'])
        self.send_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #000000;
                border-radius: 8px;
                color: {self.accent_color};
                font-size: 20px;
                border: none;
                padding: 0;
                margin: 0;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: #111111;
            }}
        """)
        self.avatar_widget.set_loading(False)

    def _take_region_screenshot(self):
        self.hide()
        self.lower()
        time.sleep(0.1)
        try:
            self.command_active = False
            self.command_state = UICommandState.READY
            self.avatar_widget.set_loading(True)
            screenshot = self.screenshot_handler.capture_region_interactive()
            if screenshot:
                self._process_screenshot(screenshot)
        except Exception as e:
            self.logger.error(f"Screenshot error: {str(e)}")
            self.avatar_widget.set_loading(False)
        finally:
            self.show()
            self.raise_()
            self.activateWindow()

    def _take_fullscreen_screenshot(self):
        self.hide()
        self.lower()
        time.sleep(0.1)
        try:
            self.avatar_widget.set_loading(True)
            screenshot = self.screenshot_handler.capture_full_screen()
            if screenshot:
                self._process_screenshot(screenshot)
        finally:
            self.show()
            self.raise_()
            self.activateWindow()

    def _process_screenshot(self, image):
        if not hasattr(self, '_thread_pool'):
            self._thread_pool = []
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        def run_analysis():
            loop.run_until_complete(self._analyze_screenshot(image))
        thread = threading.Thread(target=run_analysis)
        self._thread_pool.append(thread)
        thread.start()

    async def _analyze_screenshot(self, image):
        try:
            if self.voice_handler._cancelled:
                self.logger.info("Re-enabling cancelled voice handler for screenshot analysis...")
                self.voice_handler.uncancel()

            if self.screenshot_analyzer:
                await self.screenshot_analyzer.analyze_screenshot(
                    image,
                    self.crypto_analyzer,
                    self.notification,
                    self.voice_handler
                )
            else:
                analysis = await self.crypto_analyzer.analyze_image(image)
                if analysis:
                    # Add an assistant bubble with analysis text
                    self._append_chat_bubble({'type': 'response', 'content': analysis})
                    self.voice_handler.generate_and_play_background(analysis)
        except Exception as e:
            self.logger.error(f"Analysis error: {str(e)}")
        finally:
            self.avatar_widget.set_loading(False)

    def _toggle_voice_command(self):
        self.logger.debug("Voice button clicked")
        if self.voice_loop:
            self.voice_button.is_recording = not self.voice_button.is_recording
            if self.voice_button.is_recording:
                asyncio.run_coroutine_threadsafe(self._start_voice_recording(), self.voice_loop)
            else:
                asyncio.run_coroutine_threadsafe(self._stop_voice_recording(), self.voice_loop)
            self.voice_button._setup_styling()
        else:
            self.logger.error("No voice_loop available for toggling voice command")

    async def _start_voice_recording(self):
        try:
            self.logger.debug("Starting voice recording")
            await self.voice_command_handler.start_recording()
        except Exception as e:
            self.logger.error(f"Voice recording start error: {str(e)}")
            if self.voice_button.is_recording:
                self.voice_button.toggle_recording()

    async def _stop_voice_recording(self):
        try:
            self.logger.debug("Stopping voice recording")
            await self.voice_command_handler.stop_recording()
        except Exception as e:
            self.logger.error(f"Voice recording stop error: {str(e)}")
            if not self.voice_button.is_recording:
                self.voice_button.toggle_recording()

    def _handle_classification_with_original(self, classification: dict, original_text: str):
        fn_name = classification["name"]
        args = classification["arguments"]
        
        if fn_name == "takeScreenshot":
            if args["full_or_region"] == "full":
                self._take_fullscreen_screenshot()
            else:
                self._take_region_screenshot()
        elif fn_name == "runCommand":
            self.command_input.setText(original_text)
            self._send_command()

    def _handle_transcription(self, text: str):
        self.logger.debug(f"Got transcription: {text}")
        if not text:
            return

    def _on_command_executing(self):
        self.logger.debug("Voice command execution started")
        
    def _on_command_completed(self):
        self.logger.debug("Voice command execution completed")

    def _start_drag(self, event):
        if event.button() == Qt.LeftButton:
            if not self.close_btn.geometry().contains(  # Changed from close_btn_ref to close_btn
                self.close_btn.mapFromGlobal(event.globalPos())
            ):
                self._drag_pos = event.globalPos()
            else:
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def _on_drag(self, event):
        if self._drag_pos:
            delta = event.globalPos() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_pos = event.globalPos()

    def mousePressEvent(self, event):
        self._start_drag(event)

    def mouseMoveEvent(self, event):
        self._on_drag(event)

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        self.mute_btn.setText("🔈" if self.is_muted else "🔊")
        
        if self.is_muted:
            if hasattr(self, 'voice_handler'):
                self.voice_handler.cancel_all()
        else:
            if hasattr(self, 'voice_handler'):
                self.voice_handler.uncancel()

    def run(self):
        self.logger.info("Agent UI Starting...")
        self.show()
        self.raise_()
        self.activateWindow()

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        * {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
    """)
    window = AgentUI({}, voice_loop=None)
    window.run()
    return app.exec_()

if __name__ == "__main__":
    sys.exit(main())
