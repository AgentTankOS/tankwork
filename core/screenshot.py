import platform
import subprocess
import sys
import tempfile
import os
from PIL import Image
import logging
from typing import Optional, Tuple
import time
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush

class RegionSelectorWidget(QWidget):
    """Qt-based region selector overlay"""
    def __init__(self):
        super().__init__(None)
        # Set the proper window flags for overlay behavior
        self.setWindowFlags(
            Qt.FramelessWindowHint |  # No window frame
            Qt.WindowStaysOnTopHint |  # Stay on top
            Qt.Tool  # Don't show in taskbar
        )
        
        # Critical attributes for proper overlay behavior
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground)
        
        # Get screen and set geometry to cover entire screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        
        # Selection variables
        self.start_pos = None
        self.current_pos = None 
        self.selection_rect = None
        self.final_rect = None
        
        # Set cursor
        self.setCursor(Qt.CrossCursor)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Semi-transparent dark overlay
        overlay = QColor(0, 0, 0, 128)  # 50% opacity black
        painter.fillRect(self.rect(), overlay)
        
        # Draw selection area if active
        if self.selection_rect:
            # Clear the selected area
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(self.selection_rect, Qt.transparent)
            
            # Draw the red rectangle border
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor('#ff4a4a'), 2)
            painter.setPen(pen)
            painter.drawRect(self.selection_rect)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, QSize())
            self.update()
            
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.start_pos:
            self.current_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, self.current_pos).normalized()
            self.update()
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selection_rect:
            if self.selection_rect.width() > 10 and self.selection_rect.height() > 10:
                self.final_rect = self.selection_rect
                self.close()
            else:
                self.selection_rect = None
                self.update()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

class ScreenshotHandler:
    """Handle cross-platform screenshot capabilities with multiple fallback options"""
    def __init__(self):
        self.logger = logging.getLogger('CryptoAnalyzer.Screenshot')
        self.system = platform.system()
        self.capture_method = self._determine_capture_method()
        
    def _determine_capture_method(self) -> str:
        """Determine the best available screenshot method for the current system"""
        if self.system == "Darwin":  # macOS
            methods = [
                ('screencapture', self._check_screencapture),
                ('quartz', self._check_quartz),
                ('pillow', self._check_pillow)
            ]
        elif self.system == "Windows":
            methods = [
                ('windows_api', self._check_windows_api),
                ('mss', self._check_mss),
                ('pillow', self._check_pillow)
            ]
        else:  # Linux
            methods = [
                ('xlib', self._check_xlib),
                ('gnome_screenshot', self._check_gnome_screenshot),
                ('scrot', self._check_scrot),
                ('pillow', self._check_pillow)
            ]

        # Try each method in order
        for method, check_func in methods:
            try:
                if check_func():
                    self.logger.info(f"Using {method} for screenshots")
                    return method
            except Exception as e:
                self.logger.debug(f"Method {method} unavailable: {str(e)}")
                
        raise RuntimeError("No valid screenshot method available")

    def _check_screencapture(self) -> bool:
        """Check if macOS screencapture is available"""
        try:
            result = subprocess.run(['which', 'screencapture'], 
                                capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False

    def _check_quartz(self) -> bool:
        """Check if Quartz (CoreGraphics) is available"""
        try:
            import Quartz
            return True
        except:
            return False

    def _check_windows_api(self) -> bool:
        """Check if Win32 API components are available"""
        try:
            import win32gui
            import win32ui
            import win32con
            return True
        except:
            return False

    def _check_mss(self) -> bool:
        """Check if mss screen capture is available"""
        try:
            import mss
            return True
        except:
            return False

    def _check_xlib(self) -> bool:
        """Check if Xlib is available"""
        try:
            from Xlib import display
            display.Display().screen()
            return True
        except:
            return False

    def _check_gnome_screenshot(self) -> bool:
        """Check if gnome-screenshot is available"""
        try:
            result = subprocess.run(['which', 'gnome-screenshot'], 
                                capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False

    def _check_scrot(self) -> bool:
        """Check if scrot is available"""
        try:
            result = subprocess.run(['which', 'scrot'], 
                                capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False

    def _check_pillow(self) -> bool:
        """Check if PIL ImageGrab is available"""
        try:
            from PIL import ImageGrab
            return True
        except:
            return False

    def capture_region(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """Capture a region of the screen using the best available method"""
        try:
            if self.capture_method == 'screencapture':
                return self._capture_macos_screencapture(x, y, width, height)
            elif self.capture_method == 'quartz':
                return self._capture_macos_quartz(x, y, width, height)
            elif self.capture_method == 'windows_api':
                return self._capture_windows_api(x, y, width, height)
            elif self.capture_method == 'mss':
                return self._capture_mss(x, y, width, height)
            elif self.capture_method == 'xlib':
                return self._capture_xlib(x, y, width, height)
            elif self.capture_method == 'gnome_screenshot':
                return self._capture_gnome_screenshot(x, y, width, height)
            elif self.capture_method == 'scrot':
                return self._capture_scrot(x, y, width, height)
            elif self.capture_method == 'pillow':
                return self._capture_pillow(x, y, width, height)
            
        except Exception as e:
            self.logger.error(f"Screenshot capture failed with {self.capture_method}: {str(e)}")
            # Try fallback to Pillow if primary method fails
            if self.capture_method != 'pillow':
                try:
                    self.logger.info("Attempting fallback to Pillow")
                    return self._capture_pillow(x, y, width, height)
                except Exception as pillow_error:
                    self.logger.error(f"Pillow fallback failed: {str(pillow_error)}")
            raise

    def _capture_macos_screencapture(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using macOS screencapture utility"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            temp_path = tmp.name
        
        try:
            region = f"{int(x)},{int(y)},{int(width)},{int(height)}"
            subprocess.run([
                'screencapture',
                '-x',  # No sound
                '-R', region,
                temp_path
            ], check=True)
            
            with Image.open(temp_path) as img:
                screenshot = img.copy()
            
            return screenshot
        finally:
            os.unlink(temp_path)

    def _capture_macos_quartz(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using Quartz (CoreGraphics) on macOS"""
        import Quartz
        import CoreGraphics
        
        # Get the display ID
        main_display = Quartz.CGMainDisplayID()
        
        # Create CGRect for region
        region = CoreGraphics.CGRectMake(x, y, width, height)
        
        # Create screenshot
        image_ref = Quartz.CGDisplayCreateImageForRect(main_display, region)
        
        # Convert to PNG data
        data_provider = Quartz.CGImageGetDataProvider(image_ref)
        data = Quartz.CGDataProviderCopyData(data_provider)
        
        # Convert to PIL Image
        import io
        bytes_io = io.BytesIO(data)
        return Image.open(bytes_io)

    def _capture_windows_api(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using Windows API"""
        import win32gui
        import win32ui
        import win32con
        from ctypes import windll
        
        # Get the desktop window
        hdesktop = win32gui.GetDesktopWindow()
        
        # Create device contexts and bitmap
        desktop_dc = win32gui.GetWindowDC(hdesktop)
        img_dc = win32ui.CreateDCFromHandle(desktop_dc)
        mem_dc = img_dc.CreateCompatibleDC()
        
        try:
            # Create bitmap
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(img_dc, width, height)
            mem_dc.SelectObject(bitmap)
            
            # Copy screen to bitmap
            mem_dc.BitBlt((0, 0), (width, height), img_dc, (x, y), win32con.SRCCOPY)
            
            # Convert bitmap to PIL Image
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )
            
            return image
        finally:
            # Clean up
            mem_dc.DeleteDC()
            win32gui.DeleteObject(bitmap.GetHandle())
            win32gui.ReleaseDC(hdesktop, desktop_dc)

    def _capture_mss(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using mss library"""
        import mss
        import mss.tools
        
        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": width, "height": height}
            screenshot = sct.grab(monitor)
            return Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    def _capture_xlib(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using Xlib on Linux"""
        from Xlib import display, X
        
        d = display.Display()
        root = d.screen().root
        
        screenshot = root.get_image(x, y, width, height, X.ZPixmap, 0xffffffff)
        
        # Convert to PIL Image
        return Image.frombytes("RGB", (width, height), screenshot.data, "raw", "BGRX")

    def _capture_gnome_screenshot(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using gnome-screenshot"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            temp_path = tmp.name
        
        try:
            subprocess.run([
                'gnome-screenshot',
                '-a',  # Area selection
                '-f', temp_path
            ], check=True)
            
            with Image.open(temp_path) as img:
                return img.copy()
        finally:
            os.unlink(temp_path)

    def _capture_scrot(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using scrot on Linux"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            temp_path = tmp.name
        
        try:
            subprocess.run([
                'scrot',
                '-a', f'{x},{y},{width},{height}',
                temp_path
            ], check=True)
            
            with Image.open(temp_path) as img:
                return img.copy()
        finally:
            os.unlink(temp_path)

    def _capture_pillow(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture using PIL ImageGrab as last resort"""
        from PIL import ImageGrab
        bbox = (x, y, x + width, y + height)
        return ImageGrab.grab(bbox=bbox)

    def capture_region_interactive(self) -> Optional[Image.Image]:
        """Create an interactive region selection and capture it"""
        # Initialize Qt application if not already running
        if not QApplication.instance():
            app = QApplication.instance() or QApplication([])
        else:
            app = QApplication.instance()
            
        selector = RegionSelectorWidget()
        selector.show()  # Use show() instead of showFullScreen()
        selector.activateWindow()
        selector.raise_()
        
        # Wait for selection
        while selector.isVisible():
            app.processEvents()
            
        # Check if we have a valid selection
        if hasattr(selector, 'final_rect') and selector.final_rect:
            rect = selector.final_rect
            # Small delay before capture to allow overlay to close
            time.sleep(0.1)
            return self.capture_region(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height()
            )
            
        return None

    def capture_full_screen(self) -> Optional[Image.Image]:
        """Capture the entire screen"""
        width, height = self.get_screen_size()
        return self.capture_region(0, 0, width, height)

    def get_screen_size(self) -> Tuple[int, int]:
        """Get the primary screen size"""
        if self.system == "Darwin":
            import Quartz
            main_display = Quartz.CGMainDisplayID()
            width = Quartz.CGDisplayPixelsWide(main_display)
            height = Quartz.CGDisplayPixelsHigh(main_display)
            return width, height
        elif self.system == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        else:
            # Linux - try Xlib first
            try:
                from Xlib import display
                d = display.Display()
                screen = d.screen()
                return screen.width_in_pixels, screen.height_in_pixels
            except:
                # Fallback to Pillow
                from PIL import ImageGrab
                with ImageGrab.grab() as img:
                    return img.size