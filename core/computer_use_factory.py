from typing import Dict, Any
from .computer_use_interface import BaseComputerUseProvider, ComputerUseProvider
from .computer_use_tank import TankHandler

def get_computer_use_handler(
    config: Dict[str, Any]
) -> BaseComputerUseProvider:
    """Factory function to get the tank handler"""
    # Get model provider from config
    model_provider = config.get('computer_use', {}).get('model_provider')
    
    # Create provider configuration
    provider = ComputerUseProvider.from_string(model_provider)
    
    # Return tank handler
    return TankHandler(config)