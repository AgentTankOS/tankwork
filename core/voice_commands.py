# File: core/voice_commands.py

import asyncio
import logging
from typing import Optional, Dict, Any
import sounddevice as sd
import numpy as np
import base64
import wave
import io

from PySide6.QtWidgets import QPushButton, QWidget
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, Property, QObject
from PySide6.QtGui import QColor

# NEW/UPDATED CODE
import json
from openai import AsyncOpenAI

class VoiceCommandButton(QPushButton):
    """Voice command button with recording state"""
    recordingStarted = Signal()
    recordingStopped = Signal()
    transcriptionComplete = Signal(str)  # Fired after we get raw transcribed text

    def __init__(self, parent: Optional[QWidget] = None, accent_color: str = "#ff4a4a"):
        super().__init__(parent)
        self.accent_color = accent_color
        self.setFixedSize(36, 36)
        self.setText("🎤")
        self.setCursor(Qt.PointingHandCursor)
        self.is_recording = False
        
        # Initialize the property
        self._recording_opacity = 1.0
        
        # Create property animation for pulsing effect
        self.pulse_animation = QPropertyAnimation(self, b"recording_opacity")
        self.pulse_animation.setDuration(1000)
        self.pulse_animation.setStartValue(1.0)
        self.pulse_animation.setEndValue(0.5)
        self.pulse_animation.setLoopCount(-1)
        
        self._setup_styling()
        self.logger = logging.getLogger('VoiceCommandButton')
        self.setToolTip("Click to start recording")

    def get_recording_opacity(self):
        return self._recording_opacity

    def set_recording_opacity(self, value):
        self._recording_opacity = value
        self._setup_styling()

    recording_opacity = Property(float, get_recording_opacity, set_recording_opacity)

    def _setup_styling(self) -> None:
        """Set up button styling based on state"""
        if self.is_recording:
            # Recording state with opacity animation
            opacity = int(self._recording_opacity * 255)  # Convert to 0-255 range
            color = QColor(self.accent_color)
            bg_color = f"rgba({color.red()}, {color.green()}, {color.blue()}, {opacity})"
            
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    border-radius: 8px;
                    color: #000000;
                    font-size: 18px;
                    border: none;
                    padding: 0;
                    margin: 0;
                }}
            """)
            
            if not self.pulse_animation.state():
                self.pulse_animation.start()
            self.setToolTip("Recording... Click to stop")
            
        else:
            # Normal state
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #000000;
                    border-radius: 8px;
                    color: {QColor(self.accent_color).name()};
                    font-size: 18px;
                    border: none;
                    padding: 0;
                    margin: 0;
                }}
                QPushButton:hover {{
                    background-color: #111111;
                }}
            """)
            self.pulse_animation.stop()
            self.setToolTip("Click to start recording")

    def toggle_recording(self) -> None:
        """Toggle recording state and update appearance"""
        try:
            self.is_recording = not self.is_recording
            self._setup_styling()
            self.logger.debug(f"Recording toggled to: {self.is_recording}")
                    
        except Exception as e:
            self.logger.error(f"Toggle recording error: {str(e)}")
            self.is_recording = False
            self.pulse_animation.stop()
            self._recording_opacity = 1.0
            self._setup_styling()


class VoiceCommandHandler(QObject):  # Now inherits from QObject
    """Handles voice recording, transcription, and GPT function-call classification."""
    
    # Define signal as class attribute
    classificationComplete = Signal(dict, str)
    """
    classificationComplete is emitted with a dict like:
    {
        "name": "takeScreenshot" or "runCommand",
        "arguments": {
            "full_or_region": "full" or "region"
        }
    }
    or
    {
        "name": "runCommand",
        "arguments": {
            "command_text": "<the user's command>"
        }
    }
    """

    def __init__(self, config):
        super().__init__()  # Initialize QObject
        self.logger = logging.getLogger('VoiceCommandHandler')
        
        # Get API key from config
        self.api_key = config['api_keys'].get('openai')
        if not self.api_key:
            raise ValueError("OpenAI API key required for voice commands")
            
        # Initialize state
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.stream = None
        self.recorded_chunks = []  # Store chunks of audio data
        self.voice_button = None
        
        # Audio settings - match Whisper requirements
        self.sample_rate = 16000  # Whisper expects 16kHz
        self.channels = 1        # Mono audio
        self.dtype = np.int16    # 16-bit audio

        # Define tools schema (formerly functions)
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "takeScreenshot",
                    "description": "Takes a screenshot when the user wants to analyze or get opinions about what's currently visible on screen. Use this when the user refers to something they're looking at or wants your analysis of visual content. Examples: 'What do you think about this?', 'Is this a good investment?', 'Can you explain what I'm looking at?', 'Analyze this chart', 'What do you see here?', 'Does this look right to you?'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "full_or_region": {
                                "type": "string",
                                "enum": ["full", "region"]
                            }
                        },
                        "required": ["full_or_region"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "runCommand",
                    "description": "Executes an action or command when the user wants the system to do something. Use this for any requests to perform actions, navigate, or create/modify content. Examples: 'Go to Amazon', 'Open my email', 'Create a new document', 'Search for flights to Paris', 'Install Visual Studio Code', 'Toggle dark mode', 'Increase the volume'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command_text": {
                                "type": "string",
                                "description": "The user-intended command text"
                            }
                        },
                        "required": ["command_text"]
                    }
                }
            }
        ]
        
    def set_voice_button(self, button):
        """Set reference to UI button"""
        self.voice_button = button

    async def start_recording(self) -> None:
        """Start audio recording"""
        try:
            self.recorded_chunks = []  # Reset chunks
            
            # Initialize and start audio stream
            self.stream = sd.InputStream(
                channels=self.channels,
                samplerate=self.sample_rate,
                dtype=self.dtype,
                callback=self._audio_callback,
                blocksize=1024,
                latency='low'
            )
            self.stream.start()
            self.logger.info("Audio recording started")
            
        except Exception as e:
            self.logger.error(f"Recording start error: {str(e)}")
            raise
            
    def _audio_callback(self, indata, frames, time, status) -> None:
        """Handle incoming audio data"""
        if status:
            self.logger.warning(f"Audio callback status: {status}")
        self.recorded_chunks.append(indata.copy())
            
    async def stop_recording(self) -> None:
        """Stop recording, transcribe, then classify with GPT function-calling."""
        try:
            # Stop and close the stream
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None

            # Check if we have recorded anything
            if not self.recorded_chunks:
                self.logger.warning("No audio recorded")
                return

            # Combine chunks into single numpy array
            audio_data = np.concatenate(self.recorded_chunks, axis=0)
            
            # Save as WAV file in memory
            temp_buffer = io.BytesIO()
            with wave.open(temp_buffer, 'wb') as wav:
                wav.setnchannels(self.channels)
                wav.setsampwidth(2)  # 16-bit
                wav.setframerate(self.sample_rate)
                wav.writeframes(audio_data.tobytes())
            temp_buffer.seek(0)
            
            # Transcribe using Whisper
            try:
                response = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=("audio.wav", temp_buffer, "audio/wav")
                )
                transcript_text = response.text if hasattr(response, 'text') else str(response)
                
                # Emit raw transcriptionComplete signal
                if transcript_text and self.voice_button:
                    self.logger.debug(f"Transcription received: {transcript_text}")
                    self.voice_button.transcriptionComplete.emit(transcript_text)
                
                # Call GPT function router
                if transcript_text.strip():
                    classification = await self._classify_intent_with_gpt(transcript_text.strip())
                    if classification:
                        # Pass both classification and original transcript
                        self.classificationComplete.emit(classification, transcript_text.strip())

            except Exception as e:
                self.logger.error(f"Transcription error: {str(e)}")
                raise

            self.logger.info("Recording stopped and transcribed")
            
        except Exception as e:
            self.logger.error(f"Stop recording error: {str(e)}")
            raise
        finally:
            self.recorded_chunks = []  # Clear chunks

    async def _classify_intent_with_gpt(self, user_input: str) -> Dict[str, Any]:
        """
        Sends the transcribed text to GPT with tools definitions
        so GPT can choose either 'takeScreenshot' or 'runCommand'.
        """
        try:
            completion = await self.client.chat.completions.create(
                model="gpt-4o",  # Fixed typo in model name from gpt-4o to gpt-4
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful AI that determines whether the user wants to:"
                            "1) Analyze something currently visible on their screen (using takeScreenshot), or"
                            "2) Perform an action or execute a command (using runCommand)"
                            "\n\n"
                            "Use takeScreenshot when the user:"
                            "- Asks for your opinion or analysis of something they're looking at"
                            "- Uses demonstrative pronouns like 'this' or 'that' referring to visible content"
                            "- Wants you to explain or evaluate something on screen"
                            "- Asks about the quality, correctness, or meaning of visible content"
                            "\n\n"
                            "Use runCommand when the user:"
                            "- Wants to navigate somewhere or open something"
                            "- Requests any kind of action or system change"
                            "- Asks you to create, modify, or interact with content"
                            "- Gives instructions for tasks to perform"
                            "\n\n"
                            "If you're unsure, consider whether the user is asking about something they're looking at (takeScreenshot) or asking you to do something (runCommand)."
                            "You must always choose one of these two functions."
                        ),
                    },
                    {
                        "role": "user",
                        "content": user_input
                    }
                ],
                tools=self.tools,
                tool_choice="auto"
            )

            # Handle the tool call response
            message = completion.choices[0].message
            if message.tool_calls:
                tool_call = message.tool_calls[0]  # Get the first tool call
                if tool_call.type == "function":
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    return {
                        "name": function_name,
                        "arguments": arguments
                    }
            
            # No tool was called
            self.logger.debug("No tool call from GPT. Possibly normal text or refusal.")
            return {}
            
        except Exception as e:
            self.logger.error(f"GPT classification error: {str(e)}")
            return {}

    async def close(self) -> None:
        """Cleanup resources"""
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None
            self.recorded_chunks = []
            self.logger.info("Voice command handler closed")
        except Exception as e:
            self.logger.error(f"Cleanup error: {str(e)}")