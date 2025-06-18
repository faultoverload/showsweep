import logging
import sys

# Handles logging setup and utilities

def setup_logging(config):
    log_level = config['general'].get('log_level', 'INFO')
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('logs/showsweep.log', encoding='utf-8')
        ]
    )
    # Optionally add log rotation, etc.

# ...other logging helpers...