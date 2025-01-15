import logging
import os
import sys
from datetime import datetime

def setup_logging():
    """Configure logging for both development and production"""
    
    # Determine if we're running from a bundle
    if getattr(sys, 'frozen', False):
        # We're running in a bundle
        if sys.platform == 'darwin':
            # Get the logs directory in the app bundle
            bundle_dir = os.path.normpath(os.path.join(
                os.path.dirname(sys.executable),
                '..',
                'Resources'
            ))
            log_dir = os.path.join(bundle_dir, 'logs')
        else:
            log_dir = os.path.join(os.path.dirname(sys.executable), 'logs')
    else:
        # We're running in a normal Python environment
        log_dir = 'logs'

    # Create logs directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)

    # Generate log filenames with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    main_log_file = os.path.join(log_dir, f'agent_{timestamp}.log')
    error_log_file = os.path.join(log_dir, f'agent_error_{timestamp}.log')
    perf_log_file = os.path.join(log_dir, f'agent_performance_{timestamp}.log')

    # Main logger configuration
    main_logger = logging.getLogger('CryptoAnalyzer')
    main_logger.setLevel(logging.DEBUG)

    # Performance logger configuration
    perf_logger = logging.getLogger('CryptoAnalyzer.Performance')
    perf_logger.setLevel(logging.DEBUG)

    # Create formatters
    main_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    perf_formatter = logging.Formatter(
        '%(asctime)s - %(message)s'
    )

    # File handlers
    main_handler = logging.FileHandler(main_log_file)
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(main_formatter)

    error_handler = logging.FileHandler(error_log_file)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(main_formatter)

    perf_handler = logging.FileHandler(perf_log_file)
    perf_handler.setLevel(logging.DEBUG)
    perf_handler.setFormatter(perf_formatter)

    # Console handler (only for development)
    if not getattr(sys, 'frozen', False):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(main_formatter)
        main_logger.addHandler(console_handler)
        perf_logger.addHandler(console_handler)

        computer_use_logger = logging.getLogger('ComputerUse')
        computer_use_logger.setLevel(logging.DEBUG)
        computer_use_logger.addHandler(console_handler)

    # Add handlers
    main_logger.addHandler(main_handler)
    main_logger.addHandler(error_handler)
    perf_logger.addHandler(perf_handler)

    # Log startup information
    main_logger.info('='*50)
    main_logger.info('Application Starting')
    main_logger.info(f'Python Version: {sys.version}')
    main_logger.info(f'Running from: {os.getcwd()}')
    main_logger.info(f'Log directory: {log_dir}')
    if getattr(sys, 'frozen', False):
        main_logger.info('Running in bundled mode')
    else:
        main_logger.info('Running in development mode')
    main_logger.info('='*50)

    return main_logger, perf_logger