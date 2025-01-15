import logging
import asyncio
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class CommandState(Enum):
    """Command execution states"""
    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

@dataclass
class CommandContext:
    """Context for a command execution"""
    command: str
    callback: Optional[Callable] = None
    timestamp: float = 0.0
    state: CommandState = CommandState.QUEUED
    error: Optional[str] = None
    result: Optional[str] = None
    task: Optional[asyncio.Task] = None

class AsyncCommandManager:
    """Manages asynchronous command execution and state"""
    
    def __init__(self, handler=None, config: Optional[Dict[str, Any]] = None):
        self.logger = logging.getLogger('CommandManager')
        self.handler = handler
        self.config = config or {}
        
        # Queue for commands
        self.queue = asyncio.Queue()
        self.current_command: Optional[CommandContext] = None
        self.is_processing = False
        self._shutdown = False
        self._current_task: Optional[asyncio.Task] = None
        
        self.command_history: list[CommandContext] = []
        self.max_history = self.config.get('command_manager', {}).get('max_history', 100)

    async def add_command(self, command: str, callback: Optional[Callable] = None) -> None:
        self.logger.info(f"Adding command to queue: {command[:100]}...")
        ctx = CommandContext(
            command=command,
            callback=callback,
            timestamp=time.time()
        )
        await self.queue.put(ctx)

    async def process_queue(self) -> None:
        """Continuously process commands from the queue."""
        self.logger.info("Starting command queue processor")
        
        while not self._shutdown:
            try:
                if self.is_processing:
                    await asyncio.sleep(0.1)
                    continue
                
                ctx = await self.queue.get()
                
                try:
                    self.logger.info(f"Processing command: {ctx.command[:100]}...")
                    self.current_command = ctx
                    self.is_processing = True
                    ctx.state = CommandState.EXECUTING

                    # Create the task
                    self._current_task = asyncio.create_task(self._execute_command(ctx))

                    # Wait for the task to finish or be cancelled
                    await self._current_task
                
                except asyncio.CancelledError:
                    self.logger.info("CommandManager process_queue got cancelled.")
                    raise

                finally:
                    # Keep a history
                    if len(self.command_history) >= self.max_history:
                        self.command_history.pop(0)
                    self.command_history.append(ctx)

                    # Reset so we can pick up the next command
                    self.is_processing = False
                    self.current_command = None
                    self._current_task = None
                    self.queue.task_done()

                    self.logger.debug(
                        f"Finished handling command: {ctx.command}. "
                        f"State={ctx.state}"
                    )

            except Exception as e:
                self.logger.error(f"Queue processing error: {str(e)}")
                await asyncio.sleep(1)

        self.logger.info("Command queue processor exiting because _shutdown is True.")

    async def _execute_command(self, ctx: CommandContext) -> None:
        """Helper to run the command via the computer_use handler."""
        try:
            last_result = None
            async for result in self.handler.execute_command(ctx.command):
                if result:
                    last_result = result
                    ctx.result = result
                if ctx.callback:
                    ctx.callback(ctx)
            
            # If the final yield was "Command cancelled", set CANCELLED
            if last_result == "Command cancelled":
                self.logger.info(f"Detected 'Command cancelled' in output; marking as CANCELLED.")
                ctx.state = CommandState.CANCELLED
                ctx.error = "Command cancelled by user"
            else:
                ctx.state = CommandState.COMPLETED

        except asyncio.CancelledError:
            self.logger.info(f"Command CANCELLED: {ctx.command}")
            ctx.state = CommandState.CANCELLED
            ctx.error = "Command cancelled by user"
            if ctx.callback:
                ctx.callback(ctx)
            raise

        except Exception as e:
            self.logger.error(f"Command execution error: {str(e)}")
            ctx.state = CommandState.FAILED
            ctx.error = str(e)
            if ctx.callback:
                ctx.callback(ctx)

    async def cancel_current(self) -> None:
        """Cancel the currently executing command, if any."""
        if self.current_command and self.current_command.state == CommandState.EXECUTING:
            self.logger.info("Cancelling current command via manager")

            # 1) Let the underlying tank handler know
            await self.handler.cancel_current()

            # 2) Cancel the Python task
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
                    
            self.is_processing = False
            if self.current_command:
                self.current_command.state = CommandState.CANCELLED
                self.current_command.error = "Command cancelled by user"

                # **** CRITICAL: Immediately call the callback so UI resets ****
                if self.current_command.callback:
                    self.logger.debug("Invoking callback with CANCELLED state.")
                    self.current_command.callback(self.current_command)

            self.logger.debug("Finished cancellation in manager.")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down command manager")
        self._shutdown = True
        await self.cancel_current()
        
        while not self.queue.empty():
            try:
                ctx = self.queue.get_nowait()
                ctx.state = CommandState.CANCELLED
                ctx.error = "Command manager shutdown"
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

    def __repr__(self) -> str:
        return (f"AsyncCommandManager(processing={self.is_processing}, "
                f"queue_size={self.queue.qsize()})")
