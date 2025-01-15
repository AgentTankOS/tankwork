from elevenlabs import ElevenLabs
import logging
from datetime import datetime
import time
import os
import platform
import asyncio
import threading
import queue
import uuid
import signal

from .avatar.events import AvatarObserver
from .avatar.models import Avatar

class VoiceHandler(AvatarObserver):
    def __init__(self, config, avatar_manager=None):
        self.logger = logging.getLogger('CryptoAnalyzer.Voice')
        self.perf_logger = logging.getLogger('CryptoAnalyzer.Performance')
        self.elevenlabs_client = ElevenLabs(api_key=config['api_keys']['elevenlabs'])

        # Voice ID will be set from the avatar system
        self.voice_id = None
        self.voice_model = config.get('voice_model', 'eleven_flash_v2_5')

        # Track current playback
        self._current_player = None
        self._current_process = None
        self._cancelled = False

        # Track in-progress TTS generations (avoid duplicates)
        self._generating_texts = set()
        self._generating_lock = threading.Lock()

        # Possibly get initial voice ID from avatar manager
        if avatar_manager:
            current_avatar = avatar_manager.get_current_avatar()
            if current_avatar:
                self.voice_id = current_avatar.voice_id
                self.logger.info(f"Initial voice set from avatar: {current_avatar.name} (ID: {self.voice_id})")
            else:
                self.logger.warning("No current avatar found for voice ID.")
        else:
            self.logger.info("VoiceHandler initialized - waiting for an avatar to set voice ID")

        # Initialize audio playback
        if platform.system() == "Darwin":  # macOS
            try:
                import AVFoundation
                import objc
                self.use_avfoundation = True
                self.AVFoundation = AVFoundation

                # Initialize audio session in constructor
                audio_session = AVFoundation.AVAudioSession.sharedInstance()
                audio_session.setCategory_error_(
                    AVFoundation.AVAudioSessionCategoryPlayback, None
                )
                audio_session.setActive_error_(True, None)
            except ImportError:
                self.use_avfoundation = False
        else:
            self.use_avfoundation = False

        # Single-thread playback => no overlapping audio
        self._playback_queue = queue.Queue()
        self._stop_playback_thread = False

        # Start up the playback thread
        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            name="VoicePlaybackWorker",
            daemon=True
        )
        self._playback_thread.start()

    def cancel_all(self):
        """
        Cancel all current and pending audio operations:
        - No new TTS is generated,
        - Currently playing audio is stopped,
        - Playback queue is cleared,
        - Future attempts to generate TTS must call uncancel().
        """
        self._cancelled = True
        self.logger.debug("VoiceHandler: cancel_all() -> setting _cancelled = True")
        self.stop_current_playback()
        self.clear_queue()
        with self._generating_lock:
            self._generating_texts.clear()

    def uncancel(self):
        """Re-enable voice after prior cancellation."""
        if not self._cancelled:
            return

        self.logger.debug("VoiceHandler: uncancel() called - re-enabling voice generation.")
        self._cancelled = False
        
        # Clear any stale state
        self.clear_queue()
        self.stop_current_playback()

        # Ensure audio session is active (macOS)
        if self.use_avfoundation:
            try:
                audio_session = self.AVFoundation.AVAudioSession.sharedInstance()
                audio_session.setCategory_error_(
                    self.AVFoundation.AVAudioSessionCategoryPlayback, None
                )
                audio_session.setActive_error_(True, None)
                self.logger.debug("VoiceHandler: reactivated AVAudioSession for playback.")
            except Exception as e:
                self.logger.error(f"Error reactivating audio session in uncancel(): {e}")

        # Optionally also ensure nothing leftover is playing:
        self.stop_current_playback()

    def clear_queue(self):
        """Clear pending audio files from the playback queue."""
        try:
            while not self._playback_queue.empty():
                self._playback_queue.get_nowait()
                self._playback_queue.task_done()
        except Exception as e:
            self.logger.error(f"Error clearing voice queue: {e}")

    def stop_current_playback(self):
        """Stop any currently playing audio."""
        try:
            # If using AVFoundation:
            if self.use_avfoundation and self._current_player:
                self._current_player.stop()
                self._current_player = None
            # Otherwise if on macOS fallback or other platforms:
            elif platform.system() == "Darwin" and self._current_process:
                try:
                    os.killpg(os.getpgid(self._current_process.pid), signal.SIGTERM)
                except:
                    pass
                self._current_process = None
        except Exception as e:
            self.logger.error(f"Error stopping playback: {e}")

    def on_avatar_changed(self, avatar: Avatar) -> None:
        """Called whenever the avatar changes, to update the voice if needed."""
        if avatar is None:
            self.logger.warning("Received None avatar in on_avatar_changed")
            return
        old_id = self.voice_id
        self.voice_id = avatar.voice_id
        self.logger.info(f"Voice ID changed from {old_id} to {self.voice_id} for avatar {avatar.name}")

    def generate_and_play_background(self, text, symbol=None):
        """
        Fire-and-forget: Generate TTS in background, then enqueue for playback.
        If _cancelled is True, skip generation and playback entirely.
        """
        if self._cancelled:
            self.logger.debug("generate_and_play_background() -> skip because _cancelled is True")
            return

        with self._generating_lock:
            if text in self._generating_texts:
                self.logger.debug(f"Already generating audio for text: {text[:50]}...")
                return
            self._generating_texts.add(text)

        def bg_worker():
            try:
                if self._cancelled:
                    return
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                filename = loop.run_until_complete(self._generate_audio_file(text, symbol))
                loop.close()

                if filename and not self._cancelled:
                    self._playback_queue.put(filename)
            except Exception as e:
                self.logger.error(f"Background TTS generation error: {e}")
            finally:
                # Safely discard to avoid KeyError if already removed
                with self._generating_lock:
                    self._generating_texts.discard(text)

        threading.Thread(target=bg_worker, daemon=True).start()

    async def generate_and_play(self, text, symbol=None):
        """
        If you want to wait for the TTS file to generate, use this.
        Playback is still queued, so returns as soon as the file is created.
        """
        if self._cancelled or not self.voice_id:
            return ""

        filename = await self._generate_audio_file(text, symbol)
        if filename and not self._cancelled:
            self._playback_queue.put(filename)
        return filename

    async def _generate_audio_file(self, text, symbol=None) -> str:
        """
        Creates an MP3 from TTS; does not block playback. If cancelled, returns "".
        """
        if self._cancelled or not self.voice_id:
            return ""

        start_time = time.time()
        self.perf_logger.info(f"VOICE_GEN_START|symbol={symbol}|text_length={len(text)}")

        try:
            self.logger.info("Generating voice in background...")

            # Do TTS
            tts_start = time.time()
            audio = self.elevenlabs_client.text_to_speech.convert(
                voice_id=self.voice_id,
                model_id=self.voice_model,
                text=text
            )
            tts_duration = time.time() - tts_start
            self.perf_logger.debug(f"VOICE_TTS_CONVERT|duration={tts_duration:.3f}s")

            if self._cancelled:
                return ""

            # Unique filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            unique_id = str(uuid.uuid4())[:8]
            if symbol:
                filename = f"analysis_{symbol}_{timestamp}_{unique_id}.mp3"
            else:
                filename = f"analysis_{timestamp}_{unique_id}.mp3"

            # Save to disk
            save_start = time.time()
            chunk_count = 0
            total_bytes = 0
            with open(filename, 'wb') as f:
                for chunk in audio:
                    if self._cancelled:
                        return ""
                    if isinstance(chunk, bytes):
                        chunk_count += 1
                        total_bytes += len(chunk)
                        f.write(chunk)

            save_duration = time.time() - save_start
            self.perf_logger.debug(
                f"VOICE_FILE_SAVE|chunks={chunk_count}|bytes={total_bytes}|duration={save_duration:.3f}s"
            )
            self.logger.info(f"Saved audio (background) to: {filename}")

            total_duration = time.time() - start_time
            self.perf_logger.info(
                f"VOICE_GEN_END|symbol={symbol}|total_duration={total_duration:.3f}s|"
                f"tts_duration={tts_duration:.3f}s|save_duration={save_duration:.3f}s"
            )
            return filename

        except Exception as e:
            total_duration = time.time() - start_time
            self.logger.error(f"Background voice generation failed: {e}")
            self.perf_logger.error(
                f"VOICE_GEN_ERROR|symbol={symbol}|error={e}|duration={total_duration:.3f}s"
            )
            return ""

    def _playback_worker(self):
        """
        Continuously takes filenames from the queue, playing them one at a time.
        """
        while not self._stop_playback_thread:
            try:
                filename = self._playback_queue.get(True)
                if not filename or self._cancelled:
                    continue
                self._play_audio_blocking(filename)
                self._playback_queue.task_done()
            except Exception as e:
                self.logger.error(f"Playback worker error: {e}")
                time.sleep(0.2)

    def _play_audio_blocking(self, filename: str):
        """
        Actually do blocking playback using AVFoundation or fallback (afplay/playsound).
        If `_cancelled` goes True during playback, we break out early.
        """
        if self._cancelled:
            return

        start_time = time.time()
        self.perf_logger.info(f"AUDIO_PLAY_START|file={filename}")
        try:
            success = False
            if self.use_avfoundation:
                success = self.play_audio_macos(filename)

            if not success and not self._cancelled:
                success = self.play_audio_fallback(filename)

            duration = time.time() - start_time
            if success and not self._cancelled:
                self.perf_logger.info(f"AUDIO_PLAY_END|file={filename}|duration={duration:.3f}s")
            else:
                raise Exception("Audio playback failed")
        except Exception as e:
            self.logger.error(f"Error playing audio file {filename}: {e}")
            self.perf_logger.error(
                f"AUDIO_PLAY_ERROR|file={filename}|error={e}|duration={time.time() - start_time:.3f}s"
            )

    def play_audio_macos(self, filename):
        """Blocking playback with AVFoundation on macOS."""
        try:
            if self._cancelled:
                return False

            url = self.AVFoundation.NSURL.fileURLWithPath_(filename)
            player = self.AVFoundation.AVAudioPlayer.alloc().initWithContentsOfURL_error_(url, None)[0]
            if not player:
                return False

            self._current_player = player
            player.prepareToPlay()
            player.setRate_(1.1)
            player.play()

            while player.isPlaying() and not self._cancelled:
                time.sleep(0.1)

            self._current_player = None
            return not self._cancelled
        except Exception as e:
            self.logger.error(f"AVFoundation playback error: {e}")
            return False

    def play_audio_fallback(self, filename):
        """Blocking fallback method (afplay on macOS or playsound elsewhere)."""
        try:
            if self._cancelled:
                return False

            if platform.system() == "Darwin":
                import subprocess
                self._current_process = subprocess.Popen(
                    ['afplay', '-r', '1.1', filename],
                    preexec_fn=os.setsid  # separate process group
                )
                self._current_process.wait()
                self._current_process = None
                return not self._cancelled
            else:
                from playsound import playsound
                playsound(filename)
                return not self._cancelled

        except Exception as e:
            self.logger.error(f"Fallback playback error: {e}")
            return False

    async def text_to_speech(self, text):
        """
        Convert text to speech without playing it. 
        Just saves the MP3 and returns the filename (or None if error/cancelled).
        """
        if self._cancelled or not self.voice_id:
            return None

        start_time = time.time()
        self.perf_logger.info(f"TTS_START|text_length={len(text)}")

        try:
            tts_start = time.time()
            audio = self.elevenlabs_client.text_to_speech.convert(
                voice_id=self.voice_id,
                model_id=self.voice_model,
                text=text
            )
            tts_duration = time.time() - tts_start
            self.perf_logger.debug(f"TTS_CONVERT|duration={tts_duration:.3f}s")

            if self._cancelled:
                return None

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            unique_id = str(uuid.uuid4())[:8]
            filename = f"speech_{timestamp}_{unique_id}.mp3"

            save_start = time.time()
            chunk_count = 0
            total_bytes = 0
            with open(filename, 'wb') as f:
                for chunk in audio:
                    if self._cancelled:
                        return None
                    if isinstance(chunk, bytes):
                        chunk_count += 1
                        total_bytes += len(chunk)
                        f.write(chunk)

            save_duration = time.time() - save_start
            self.perf_logger.debug(
                f"TTS_FILE_SAVE|chunks={chunk_count}|bytes={total_bytes}|duration={save_duration:.3f}s"
            )

            total_duration = time.time() - start_time
            self.perf_logger.info(
                f"TTS_END|total_duration={total_duration:.3f}s|tts_duration={tts_duration:.3f}s|"
                f"save_duration={save_duration:.3f}s"
            )
            return filename

        except Exception as e:
            total_duration = time.time() - start_time
            self.logger.error(f"Text to speech conversion failed: {e}")
            self.perf_logger.error(
                f"TTS_ERROR|error={e}|duration={total_duration:.3f}s"
            )
            return None

    def cleanup(self):
        """Stop playback thread, kill any audio processes, remove temp MP3 files."""
        try:
            self.logger.info("Cleaning up voice handler...")

            self.stop_current_playback()
            self._stop_playback_thread = True
            self._playback_queue.put("")  # sentinel to unblock
            self._playback_thread.join(timeout=2)

            if self.use_avfoundation:
                try:
                    audio_session = self.AVFoundation.AVAudioSession.sharedInstance()
                    audio_session.setActive_error_(False, None)
                except Exception as e:
                    self.logger.error(f"Error deactivating audio session: {e}")

            # Dispose of the TTS client
            if hasattr(self, 'elevenlabs_client'):
                self.elevenlabs_client = None

            # Remove temp MP3 files
            try:
                dir_path = os.getcwd()
                for fname in os.listdir(dir_path):
                    if fname.startswith(('analysis_', 'speech_')) and fname.endswith('.mp3'):
                        file_path = os.path.join(dir_path, fname)
                        try:
                            os.remove(file_path)
                            self.logger.debug(f"Removed temp audio file: {fname}")
                        except Exception as ex:
                            self.logger.error(f"Error removing audio file {fname}: {ex}")
            except Exception as ex:
                self.logger.error(f"Error cleaning up temp audio files: {ex}")

            self.logger.info("Voice handler cleanup completed")

        except Exception as e:
            self.logger.error(f"Error during voice handler cleanup: {e}")
