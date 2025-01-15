import os
import sys
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger('CryptoAnalyzer.Config')

class ConfigurationError(Exception):
    """Custom exception for configuration errors"""
    pass

def get_bundle_path(relative_path: str) -> str:
    """Get correct path whether running as script or frozen app"""
    if getattr(sys, 'frozen', False):
        # Running in a bundle
        if sys.platform == 'darwin':
            # macOS bundle structure
            bundle_dir = os.path.normpath(os.path.join(
                os.path.dirname(sys.executable),
                '..',
                'Resources'
            ))
            logger.debug(f"Running from macOS bundle. Bundle dir: {bundle_dir}")
        else:
            # Windows/Linux bundle structure
            bundle_dir = os.path.dirname(sys.executable)
            logger.debug(f"Running from Windows/Linux bundle. Bundle dir: {bundle_dir}")
            
        full_path = os.path.join(bundle_dir, relative_path)
        logger.debug(f"Resolved bundle path: {full_path}")
        return full_path
    else:
        # Running in normal Python environment
        full_path = os.path.abspath(relative_path)
        logger.debug(f"Running in development. Path: {full_path}")
        return full_path

def ensure_paths_exist():
    """Ensure all required paths exist"""
    required_paths = [
        'assets/avatars',  # Updated to include avatars subdirectory
        'logs',
        'config',
        'core',
        'ui',
        'core/computer_use_providers'
    ]
    
    for path in required_paths:
        full_path = get_bundle_path(path)
        if not os.path.exists(full_path):
            os.makedirs(full_path, exist_ok=True)
            logger.debug(f"Created directory: {full_path}")

def validate_api_keys(config: Dict[str, Any]) -> None:
    """Validate required API keys"""
    required_keys = [
        'GEMINI_API_KEY', 
        'OPENAI_API_KEY', 
        'ELEVENLABS_API_KEY'
    ]
    
    missing_keys = [key for key in required_keys if not os.getenv(key)]
    
    if missing_keys:
        logger.warning(f"Missing required API keys: {', '.join(missing_keys)}")

def get_computer_use_config() -> Dict[str, Any]:
    """Get computer use specific configuration"""
    # Get implementation type from ENV or default to tank
    implementation = os.getenv('COMPUTER_USE_IMPLEMENTATION', 'tank')
    
    # Base configuration
    config = {
        'implementation': implementation,
        'model': {
            'type': os.getenv('COMPUTER_USE_MODEL', 'claude-3-5-sonnet-20241022'),
            'provider': os.getenv('COMPUTER_USE_MODEL_PROVIDER', 'anthropic')
        }
    }
    
    # For backward compatibility
    config['provider'] = implementation
    
    return config

def load_config() -> Dict[str, Any]:
    """Load and validate configuration"""
    logger.debug(f"Loading config from working directory: {os.getcwd()}")
    
    # Ensure we're in the right directory for bundled app
    if getattr(sys, 'frozen', False):
        bundle_dir = os.path.join(os.path.dirname(sys.executable), '..', 'Resources')
        os.chdir(bundle_dir)
        logger.debug(f"Changed to bundle directory: {bundle_dir}")
    
    # Ensure required paths exist
    ensure_paths_exist()
    
    # Load environment variables
    env_path = get_bundle_path('.env')
    logger.debug(f"Loading .env from: {env_path}")
    load_dotenv(env_path, override=True)
    
    # Build configuration dictionary
    config = {
        'api_keys': {
            'gemini': os.getenv('GEMINI_API_KEY'),
            'openai': os.getenv('OPENAI_API_KEY'),
            'elevenlabs': os.getenv('ELEVENLABS_API_KEY'),
            'claude': os.getenv('ANTHROPIC_API_KEY'),
            'anthropic': os.getenv('ANTHROPIC_API_KEY')  # Alias for claude
        },
        'voice_model': os.getenv('ELEVENLABS_MODEL', 'eleven_flash_v2_5'),
        'ui': {
            'theme': os.getenv('UI_THEME', 'dark')
        },
        'computer_use': get_computer_use_config(),
        'logging': {
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'file_path': get_bundle_path('logs')
        },
        'narrative_processor': {
            'logger_name': os.getenv('NARRATIVE_LOGGER_NAME', 'ComputerUse.Tank'),
            'skip_strings': [
                "Initialization response:",
                "Command payload:",
                "Command response:",
                "Received estimation update",
                "Command completed successfully"
            ],
            'skip_patterns': [
                "tool use: computer",
                "input: {'action'",
                "screenshot",
                "left_click",
                "page_down",
                "performed left_click",
            ],
            'model': os.getenv('NARRATIVE_MODEL', 'gpt-4o'),
            'temperature': float(os.getenv('NARRATIVE_TEMPERATURE', '0.7')),
            'max_tokens': int(os.getenv('NARRATIVE_MAX_TOKENS', '150'))
        },
    }
    
    # Validate configuration
    validate_api_keys(config)
    
    # Log configuration summary (excluding sensitive data)
    logger.debug("Configuration loaded with:")
    logger.debug(f"- Voice model: {config['voice_model']}")
    logger.debug(f"- Theme: {config['ui']['theme']}")
    logger.debug(f"- Computer Use Implementation: {config['computer_use']['implementation']}")
    logger.debug(f"- Computer Use Model Provider: {config['computer_use']['model']['provider']}")
    logger.debug(f"- Computer Use Model: {config['computer_use']['model']['type']}")
    logger.debug("- API keys present: " + 
                 ", ".join(k for k, v in config['api_keys'].items() if v))
    logger.debug(f"- Narrative logger: {config['narrative_processor']['logger_name']}")
    
    return config

def get_config_template() -> str:
    """Get template for .env file"""
    return """# API Keys
GEMINI_API_KEY=
OPENAI_API_KEY=
ELEVENLABS_API_KEY=
ANTHROPIC_API_KEY=

# Voice Settings
ELEVENLABS_MODEL=eleven_flash_v2_5

# UI Settings
UI_THEME=dark

# Computer Use Settings
COMPUTER_USE_IMPLEMENTATION=tank
COMPUTER_USE_MODEL=claude-3-5-sonnet-20241022
COMPUTER_USE_MODEL_PROVIDER=anthropic

# Narrative Processor
NARRATIVE_LOGGER_NAME=ComputerUse.Tank
NARRATIVE_MODEL=gpt-4o-mini
NARRATIVE_TEMPERATURE=0.6
NARRATIVE_MAX_TOKENS=250

# Logging
LOG_LEVEL=INFO
"""

def create_default_env():
    """Create default .env file if it doesn't exist"""
    env_path = get_bundle_path('.env')
    if not os.path.exists(env_path):
        with open(env_path, 'w') as f:
            f.write(get_config_template())
        logger.info("Created default .env file")
        return True
    return False