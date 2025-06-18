# Plex-TVPurge Project

import os
import configparser
import logging
from cli import main_cli
from logging_utils import setup_logging
from database import DatabaseManager


def load_config():
    config = configparser.ConfigParser()
    config_path = os.environ.get('SHOWSWEEP_CONFIG', './config/config.ini')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    config.read(config_path)
    return config


def main():
    config = load_config()
    setup_logging(config)
    logging.debug("Loaded configuration and initialized logging.")
    db_path = config['general'].get('db_path', './config/SHOWSWEEP.db')
    db = DatabaseManager(db_path)
    db.setup()
    logging.debug(f"Database initialized at {db_path}.")
    main_cli(config, db)


if __name__ == "__main__":
    main()