import aiohttp
import json
import logging
from typing import Optional, Dict, Any

class GeneralCommandAccelerator:
    """General command accelerator that uses GPT-4o-mini to enhance command prompts"""
    
    def __init__(self, config: Dict[str, Any]):
        self.api_key = config['api_keys'].get('openai')
        if not self.api_key:
            raise ValueError("OpenAI API key not found in configuration")
        self.logger = logging.getLogger('CryptoAnalyzer.CommandAccelerator')
        
    async def enhance_command(self, command: str) -> Optional[str]:
        """Enhance a command using GPT-4o-mini"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                
                prompt = f"""As a command optimizer, enhance the following user command into a detailed, step-by-step instruction:

User Command: {command}

Convert this into specific, actionable steps that would help an AI assistant better understand and execute the task.
Make it more explicit and detailed while maintaining the original intent.

Respond ONLY with the enhanced command, no extra text or explanations.
IMPORTANT: DO NOT EXCEED 300 Characters total in your output."""

                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are a command optimization assistant that makes user commands more explicit and detailed."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7
                }

                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        enhanced_command = data['choices'][0]['message']['content'].strip()
                        self.logger.debug(f"Enhanced command: {enhanced_command}")
                        return enhanced_command
                    else:
                        error_text = await response.text()
                        self.logger.error(f"GPT-4o-mini API error: {error_text}")
                        return None

        except Exception as e:
            self.logger.error(f"Command enhancement error: {str(e)}")
            return None