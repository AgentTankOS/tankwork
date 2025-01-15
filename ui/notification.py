from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
    QFrame, QApplication, QPushButton)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QPoint, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont
import platform
import time

def get_display_scaling():
    """Get display scaling factor safely."""
    try:
        if platform.system() == "Darwin":  # macOS
            from AppKit import NSScreen
            return NSScreen.mainScreen().backingScaleFactor()
        return 1.0
    except:
        return 1.0

class ProgressBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0
        self.setFixedHeight(2)
        self.setStyleSheet("background-color: transparent;")
        
        self.bar = QFrame(self)
        self.bar.setStyleSheet("background-color: #ff4a4a;")
        self.bar.setFixedHeight(2)
        
    def setValue(self, value):
        self.value = value
        width = int((value / 100.0) * self.width())
        self.bar.setFixedWidth(width)

class NotificationBridge(QObject):
    """Bridge for thread-safe notification signals"""
    show_message_signal = Signal(str)

class NotificationWindow(QWidget):
    def __init__(self, parent):
        super().__init__(None)
        self.parent = parent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self.scaling_factor = get_display_scaling()
        
        self.animation_active = False
        self.current_progress = 0
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self._update_progress_bar)
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._force_hide)
        
        self.bridge = NotificationBridge()
        self.bridge.show_message_signal.connect(self._show_message_impl)
        
        self.initUI()
        
    def initUI(self):
        # Main layout
        layout = QVBoxLayout(self)
        padding = int(12 * self.scaling_factor)
        layout.setContentsMargins(padding, int(10 * self.scaling_factor), padding, padding)
        layout.setSpacing(int(6 * self.scaling_factor))

        # Close button (positioned absolutely)
        self.close_button = QPushButton("×", self)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedSize(int(14 * self.scaling_factor), int(14 * self.scaling_factor))
        self.close_button.setStyleSheet("""
            QPushButton {
                color: #999999;
                border: none;
                background: transparent;
                font-size: 14px;
                font-weight: bold;
                padding: 0;
                margin: 0;
                text-align: center;  /* Ensure text is centered */
                line-height: 14px;   /* Match the height to ensure vertical centering */
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.close_button.clicked.connect(self._force_hide)
        
        # Message label with full width
        self.message_label = QLabel()
        self.message_label.setStyleSheet("""
            color: white;
            background-color: transparent;
            padding-right: 20px;
        """)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        
        # Progress bar
        self.progress_bar = ProgressBar(self)
        layout.addWidget(self.progress_bar)

    def resizeEvent(self, event):
        # Position close button in top-right corner
        button_margin = int(8 * self.scaling_factor)
        self.close_button.move(
            self.width() - self.close_button.width() - button_margin - 15,  # Shift left by 5px
            button_margin - 5  # Shift up by 3px to align with the visible X
        )
        super().resizeEvent(event)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(
            self.rect(), 
            12,  # Fixed 12px radius
            12
        )
        
        painter.fillPath(path, QColor(0, 0, 0, 245))

    def show_message(self, message):
        self.bridge.show_message_signal.emit(message)
        
    def _show_message_impl(self, message):
        try:
            self.hide_timer.stop()
            self.progress_timer.stop()
            
            parent_pos = self.parent.pos()
            parent_width = self.parent.width()
            
            # Set max width to parent width
            max_width = parent_width
            self.setMaximumWidth(max_width)
            
            # Dynamic font size based on content with larger base size
            font_size = max(13, min(int(max_width * 0.04), 15))
            self.message_label.setStyleSheet(f"""
                color: white;
                font-size: {font_size}px;
                line-height: 1.4;
                background-color: transparent;
                padding-top: 2px;
            """)
            
            self.message_label.setText(message)
            self.message_label.adjustSize()
            
            # Set message width constraint
            message_width = self.message_label.sizeHint().width()
            padding = int(24 * self.scaling_factor)  # Account for left and right padding
            
            # Calculate optimal width
            content_width = message_width + padding
            final_width = min(content_width, max_width)
            
            # Calculate height based on content
            message_height = self.message_label.heightForWidth(final_width - padding)
            final_height = message_height + int(34 * self.scaling_factor)  # Slightly increased vertical padding for line height
            
            # Position notification
            x = parent_pos.x() + (parent_width - final_width) // 2  # Center horizontally
            y = parent_pos.y() + self.parent.height() + 10
            
            self.setFixedSize(final_width, final_height)
            self.move(x, y)
            
            self.animation_active = True
            self.current_progress = 0
            self.progress_bar.setValue(0)
            
            self.show()
            self.raise_()
            
            self.progress_timer.start(50)
            self.hide_timer.start(20000)
            
        except Exception as e:
            print(f"Error showing notification: {str(e)}")
            self.show()
            
    def _update_progress_bar(self):
        if not self.animation_active:
            return
            
        self.current_progress += 0.25
        self.progress_bar.setValue(min(self.current_progress, 100))
        
        if self.current_progress >= 100:
            self.progress_timer.stop()
            self._force_hide()
            
    def _force_hide(self):
        self.hide_timer.stop()
        self.progress_timer.stop()
        
        self.animation_active = False
        self.current_progress = 0
        self.progress_bar.setValue(0)
        
        self.close()
        super().hide()

    def closeEvent(self, event):
        self._force_hide()
        event.accept()