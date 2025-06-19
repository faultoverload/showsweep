import logging
import os
import sys

# Handles logging setup and utilities

def setup_logging(config):
    log_level = getattr(logging, config['general'].get('log_level', 'INFO').upper(), logging.INFO)
    log_file = config['general'].get('log_file', './logs/showsweep.log')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.debug(f"Logging initialized. Log file: {log_file}")
    # Optionally add log rotation, etc.

# ...other logging helpers...