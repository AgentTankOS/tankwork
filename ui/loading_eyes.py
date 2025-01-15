import math
import random
from collections import namedtuple

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QRadialGradient
)

Ring = namedtuple(
    "Ring",
    [
        "angle",     # Current rotation angle
        "radius",    # Ring radius
        "width",     # Line width
        "alpha",     # Opacity
        "speed"      # Rotation speed
    ]
)

class LaserEyeEffect(QWidget):
    """
    Enhanced loading effect with rotating glowing rings positioned
    on the outer edge of the avatar circle.
    """
    def __init__(self, parent=None, accent_color=QColor("#ff4a4a")):
        super().__init__(parent)
        self.setVisible(False)
        self.accent_color = accent_color
        
        # Ring configuration
        self.rings = []
        self.initialize_rings()
        
        # Animation timer
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update)
        self.animation_timer.start(16)  # ~60 FPS

    def initialize_rings(self):
        """Initialize the rotating rings with different properties."""
        base_speeds = [2.0, 1.5, 1.0]
        base_radii = [0.99, 0.95, 0.90]  # Positioned closer to edge
        base_widths = [7, 9, 11]  # Wider for more coverage
        base_alphas = [255, 255, 255]  # Further increased opacity
        
        self.rings = [
            Ring(
                angle=i * (360 / 3),
                radius=rad,
                width=width,
                alpha=alpha,
                speed=speed
            )
            for i, (speed, rad, width, alpha) in enumerate(
                zip(base_speeds, base_radii, base_widths, base_alphas)
            )
        ]

    def set_accent_color(self, color: QColor):
        """Update the accent color"""
        self.accent_color = color
        self.update()

    def paintEvent(self, event):
        if not self.isVisible():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        min_dim = min(w, h)
        center = QPointF(w/2, h/2)

        # Create clip path
        clip_path = QPainterPath()
        clip_path.addEllipse(center, min_dim/2, min_dim/2)
        painter.setClipPath(clip_path)

        # Draw background glow (more opaque)
        bg_gradient = QRadialGradient(center, min_dim/2)
        bg_gradient.setColorAt(0, QColor(self.accent_color.red(), 
                                       self.accent_color.green(), 
                                       self.accent_color.blue(), 30))
        bg_gradient.setColorAt(1, QColor(self.accent_color.red(), 
                                       self.accent_color.green(), 
                                       self.accent_color.blue(), 0))
        painter.fillPath(clip_path, QBrush(bg_gradient))

        # Update and draw rings
        updated_rings = []
        for ring in self.rings:
            # Update angle
            new_angle = (ring.angle + ring.speed) % 360
            
            # Calculate ring properties
            current_radius = ring.radius * (min_dim/2)
            
            # Draw ring with higher opacity using accent color
            pen = QPen()
            pen.setWidth(ring.width)
            pen.setColor(QColor(self.accent_color.red(), 
                              self.accent_color.green(), 
                              self.accent_color.blue(), 
                              ring.alpha))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            # Draw arc segments with increased length
            arc_length = 140  # degrees - increased for more coverage
            start_angle = new_angle * 16  # Qt uses 16ths of a degree
            painter.drawArc(
                int(center.x() - current_radius),
                int(center.y() - current_radius),
                int(current_radius * 2),
                int(current_radius * 2),
                start_angle,
                arc_length * 16
            )
            
            # Store updated ring
            updated_rings.append(ring._replace(angle=new_angle))
        
        self.rings = updated_rings

class LoadingEyesWidget:
    """
    Maintains compatibility with existing interface.
    """
    def __init__(self, parent_widget):
        self.parent = parent_widget
        # Get accent color from parent if available
        accent_color = QColor(parent_widget.parent().accent_color) if hasattr(parent_widget.parent(), 'accent_color') else QColor("#ff4a4a")
        self.orb = LaserEyeEffect(parent_widget, accent_color)
        self.is_loading = False
        self.update_positions()

    def set_loading(self, is_loading: bool):
        """Enable or disable the loading effect."""
        self.is_loading = is_loading
        self.orb.setVisible(is_loading)

    def update_accent_color(self, color: QColor):
        """Update the accent color of the loading effect"""
        self.orb.set_accent_color(color)

    def update_positions(self):
        """Update the effect's geometry to match the parent widget."""
        if not self.parent:
            return
        w, h = self.parent.width(), self.parent.height()
        self.orb.setGeometry(0, 0, w, h)