import logging
import asyncio
import os
from openai import AsyncOpenAI
from .avatar.events import AvatarObserver
from .avatar.models import Avatar

class NarrativeProcessor(AvatarObserver):
    """Super simple narrative processor that just speaks messages."""

    def __init__(self, config: dict, avatar_manager, voice_handler, voice_loop=None):
        self.logger = logging.getLogger('CryptoAnalyzer.NarrativeProcessor')
        self.voice_handler = voice_handler
        self.avatar_manager = avatar_manager  # Store avatar_manager reference
        
        # Add storage for current prompts
        self.current_personality = ""
        self.current_narrative = ""
        
        # Register as observer and initialize prompts
        if avatar_manager:
            avatar_manager.add_observer(self)
            current_avatar = avatar_manager.get_current_avatar()
            if current_avatar:
                self.on_avatar_changed(current_avatar)
        
        # Use provided voice_loop or fallback
        self.loop = voice_loop or asyncio.get_event_loop()
        self._queue = asyncio.Queue()
        self._shutdown = False
        self._cancelled = False
        self.processing_task = None
        self.prep_task = None
        
        # We'll store a UI reference, but we won't call UI methods from here.
        self.ui = None
        
        # Initialize OpenAI client
        self.api_key = config.get('api_keys', {}).get('openai') or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            self.logger.warning("OpenAI API key not found - using direct messages only.")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.api_key)
        
        # Narrative config
        narrative_cfg = config.get('narrative_processor', {})
        self.model = narrative_cfg.get('model', 'gpt-4o-mini')
        self.temperature = narrative_cfg.get('temperature', 0.6)
        self.max_tokens = narrative_cfg.get('max_tokens', 250)
        
        # Caching / queue config
        self.batch_size = narrative_cfg.get('batch_size', 1)
        self.cache_size = narrative_cfg.get('cache_size', 20)
        
        self._translation_cache = {}
        self._prep_queue = asyncio.Queue()

        self.logger.info("[INIT] Narrative processor initialized")

    def on_avatar_changed(self, avatar: Avatar) -> None:
        """Handle avatar change events"""
        self.current_personality = avatar.get_prompt('personality')
        self.current_narrative = avatar.get_prompt('narrative')
        self.logger.info(f"Updated prompts for avatar: {avatar.name}")

    def cancel(self):
        """Signal cancellation to stop processing."""
        self._cancelled = True
        self.clear_queues()
        if self.voice_handler:
            self.voice_handler.cancel_all()
           
    def clear_queues(self):
        """Clear both prep and message queues."""
        if not self.loop or not self.loop.is_running():
            return
        
        async def _clear():
            while not self._prep_queue.empty():
                try:
                    await self._prep_queue.get()
                    self._prep_queue.task_done()
                except:
                    pass
            while not self._queue.empty():
                try:
                    await self._queue.get()
                    self._queue.task_done()
                except:
                    pass

        asyncio.run_coroutine_threadsafe(_clear(), self.loop)

    def _should_skip_message(self, message: str) -> bool:
        """
        Check if message should be skipped entirely.
        For messages containing 'Claude: ', check only the content after it.
        """
        if "Claude: " in message:
            # Extract the content after "Claude: "
            content = message.split("Claude: ", 1)[1]
        else:
            content = message
            
        skip_patterns = [
            "Initialization response:",
            "Command payload:",
            "Command response:",
            "Received estimation update",
            "'coordinate'",
            "moved mouse to (",
            "'return'",
            "'Return'",
            "pressed keys: return",
            "'delete'",
            "pressed keys: delete",
            "ctrl+a",
            "'ctrl+a'",
            "moved mouse to ",
            "tool use: computer",
            "input: {'action'",
            "'screenshot'",
            "'left_click'",
            "mouse_move",
            "'key'",
            "Tool executed: screenshot"
        ]
        content_lower = content.lower()
        return any(pattern.lower() in content_lower for pattern in skip_patterns)

    async def _translate_message(self, message: str) -> str:
        """
        Translate message using OpenAI if available, to produce a concise, 
        fun summary of what's going on.
        """
        if not self.client or self._cancelled:
            return message

        # Check cache first
        if message in self._translation_cache:
            return self._translation_cache[message]

        try:
            # Updated system prompt to include personality and narrative
            system_prompt = f"""

            YOUR PERSONALITY:
            {self.current_personality}
            
            YOUR NARRATIVE TRANSLATION STYLE:
            {self.current_narrative}
            

            Additional Instructions:
            Be concise.
            The text you receive are logs of actions and content that is on the screen of a computer.
            You are an ai agent navigating this computer. Translate the text so that you narrate what's going on.
            For tool use messages, be fun with them and summarize them.
            Be brief and don't include coordinates or reply with the exact message.
            Maintain the core meaning while making it sound natural.
            """

            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )

            if self._cancelled:
                return message

            # Cache result
            if len(self._translation_cache) >= self.cache_size:
                self._translation_cache.pop(next(iter(self._translation_cache)))

            translated = completion.choices[0].message.content
            self._translation_cache[message] = translated
            return translated

        except Exception as e:
            self.logger.error(f"Translation error: {str(e)}")
            return message

    async def _prepare_message(self, message: str):
        """
        Pre-process message for TTS; if "Claude: " is found, we translate that portion.
        """
        if self._cancelled:
            return message

        if "Claude: " in message:
            text = message.split("Claude: ", 1)[1]
            return await self._translate_message(text)
        return message

    def _clean_gpt_text(self, text: str) -> str:
        """
        Remove lines that contain references to tool usage. This way you don't see
        "Tool Use: computer" or "Tool executed: left_click" in the final UI bubble.
        """
        remove_if_contains = [
            "tool use:",
            "tool executed:",
            "input: {'action'",
            "left_click",
            "'screenshot'",       # optional
        ]
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            lower_line = line.lower()
            if any(pattern in lower_line for pattern in remove_if_contains):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    async def _preparation_worker(self):
        """Background task to convert raw logs into 'prepared' messages (translated, etc.)."""
        while not self._shutdown and not self._cancelled:
            try:
                while self._prep_queue.qsize() < self.batch_size and not self._queue.empty():
                    message = await self._queue.get()
                    if self._cancelled:
                        self._queue.task_done()
                        continue

                    prepared = await self._prepare_message(message)
                    if not self._cancelled:
                        await self._prep_queue.put((message, prepared))
                    self._queue.task_done()

                await asyncio.sleep(0.1)

            except Exception as e:
                self.logger.error(f"Error in preparation worker: {str(e)}")
                await asyncio.sleep(0.1)

    async def _run(self):
        """
        Main loop for processing messages. We only do TTS/UI for messages containing
        "Claude: ", ignoring all other logs. But if GPT lumps tool usage text
        with "Claude: ", we do an extra cleaning step so you don't see them.
        """
        self.logger.info(f"[START] Message processor running in loop {id(self.loop)}")

        while not self._shutdown and not self._cancelled:
            try:
                self.logger.debug(f"[QUEUE] Current size: {self._queue.qsize()}")
                self.logger.debug(f"[PREP_QUEUE] Current size: {self._prep_queue.qsize()}")
                if self._cancelled:
                    continue

                if not self._prep_queue.empty():
                    original_message, prepared_text = await self._prep_queue.get()
                else:
                    original_message = await self._queue.get()
                    prepared_text = None

                self.logger.debug(f"[PROCESS] Got message: {original_message}")
                if self._cancelled:
                    if prepared_text:
                        self._prep_queue.task_done()
                    else:
                        self._queue.task_done()
                    continue

                # Skip entirely if it matches skip patterns (no "Claude: ").
                if self._should_skip_message(original_message):
                    self.logger.debug(f"Skipping filtered message: {original_message}")
                    if prepared_text:
                        self._prep_queue.task_done()
                    else:
                        self._queue.task_done()
                    continue

                # Only do TTS/UI if message has "Claude:"
                if "Claude: " in original_message and not self._cancelled:
                    text = prepared_text if prepared_text else original_message.split("Claude: ", 1)[1]
                    self.logger.debug(f"[VOICE] SENDING to voice handler: {text}")
                    try:
                        # If not pre-translated, do it now
                        if not prepared_text and not self._cancelled:
                            text = await self._translate_message(text)

                        if not self._cancelled:
                            # Remove lines like "Tool executed: left_click" from final text
                            text = self._clean_gpt_text(text)

                            self.logger.info(f"[ASSISTANT] GPT processed message: {text}")

                            # Send to TTS
                            self.voice_handler.generate_and_play_background(text)
                            self.logger.debug("[VOICE] Sent to voice handler successfully")

                            # Emit to UI only for the final "Claude" logs
                            if self.ui and hasattr(self.ui, 'logMessageSignal'):
                                self.ui.logMessageSignal.emit({
                                    'type': 'response',
                                    'content': text
                                })

                    except Exception as ve:
                        self.logger.error(f"[VOICE] Error in voice handler: {ve}")

                # Mark tasks done
                if prepared_text:
                    self._prep_queue.task_done()
                else:
                    self._queue.task_done()

            except Exception as e:
                self.logger.error(f"[ERROR] Error in message processing: {str(e)}")
                await asyncio.sleep(0.1)

    async def start(self):
        """Kick off the preparation + processing tasks if not already started."""
        if not self.processing_task:
            self._cancelled = False
            self.prep_task = self.loop.create_task(self._preparation_worker())
            self.processing_task = self.loop.create_task(self._run())
            self.logger.info(f"[START] Created processor tasks in loop {id(self.loop)}")

    def resume(self):
        """Resume after .cancel(). Clears queues and restarts tasks."""
        if not self._cancelled:
            return

        self.logger.info("Resuming narrative processor after cancellation...")
        self._cancelled = False
        self.clear_queues()
        self.processing_task = None
        self.prep_task = None

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.start(), self.loop)

    async def process_message(self, message: str):
        """
        Add message to the queue for possible TTS or UI display.
        We only proceed if the message is not cancelled.
        """
        if self._cancelled:
            return

        if not self.processing_task:
            self.logger.warning("[QUEUE] Processor not started, starting now...")
            await self.start()

        await self._queue.put(message)
        self.logger.debug(f"[QUEUE] Added message: {message}")

    async def close(self):
        """Shutdown the narrative processor tasks."""
        self.logger.info("[SHUTDOWN] Shutting down narrative processor")
        self._shutdown = True
        self._cancelled = True
        self.clear_queues()

        for task in [self.processing_task, self.prep_task]:
            if task:
                try:
                    task.cancel()
                    await task
                except asyncio.CancelledError:
                    pass

        if self.client:
            await self.client.close()

        self.logger.info("[SHUTDOWN] Narrative processor shutdown complete")


class NarrativeHandler(logging.Handler):
    """
    Logging handler that captures logs from EXACTLY 'ComputerUse.TankHandler' at INFO level.
    We only pass messages containing "Claude: " to the UI, after possible skip-checks,
    and also feed them to the narrative queue so it can do TTS if needed.

    If you ONLY want the final GPT messages to appear in the UI, rely on 
    the 'self.logger.info("[ASSISTANT] GPT processed...")' calls above
    and remove or down-tune this handler as needed.
    """

    def __init__(self, processor, logger_name):
        super().__init__()
        self.processor = processor
        self.logger_name = logger_name
        self.logger = logging.getLogger('CryptoAnalyzer.NarrativeHandler')
        self._last_message = None

    def emit(self, record):
        # Only handle logs from EXACTLY self.logger_name at INFO
        if record.levelno != logging.INFO or record.name != self.logger_name:
            return

        message = record.getMessage()
        if message == self._last_message:
            # skip repeated identical messages
            return

        self._last_message = message
        self.logger.debug(f"[HANDLER] Got message: {message}")

        # Only pass it to the queue if there's a running loop
        loop = self.processor.loop
        if loop and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.processor.process_message(message),
                    loop
                )
                # optional: future.result(timeout=0.1)
            except asyncio.TimeoutError:
                self.logger.warning("[HANDLER] Timed out queueing message.")
            except Exception as e:
                self.logger.error(f"[HANDLER] Error queueing message: {e}")
        else:
            self.logger.error("[HANDLER] No running event loop available")


def setup_narrative_processor(config: dict, avatar_manager, voice_handler, voice_loop=None):
    """
    Create a NarrativeProcessor, attach a NarrativeHandler that only captures 
    'ComputerUse.TankHandler' logs at INFO, then feed them into the processor's queue.
    """
    processor = NarrativeProcessor(
        config=config,
        avatar_manager=avatar_manager,
        voice_handler=voice_handler,
        voice_loop=voice_loop
    )
   
    # If the UI is attached to avatar_manager, store it
    if hasattr(avatar_manager, 'ui'):
        processor.ui = avatar_manager.ui

    logger_name = "ComputerUse.TankHandler"
    handler = NarrativeHandler(processor, logger_name)

    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)

    return processor
