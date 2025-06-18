# Handles SQLite database management

import sqlite3
import os
import time
import shutil
import logging

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        logging.debug(f"DatabaseManager initialized with db_path={db_path}")

    def setup(self):
        self.conn = sqlite3.connect(self.db_path)
        c = self.conn.cursor()
        # Create tables if not exist
        c.execute('''CREATE TABLE IF NOT EXISTS shows (
            id TEXT PRIMARY KEY,
            title TEXT,
            last_processed INTEGER,
            action TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id TEXT,
            action TEXT,
            timestamp INTEGER
        )''')
        self.conn.commit()
        logging.debug("Database tables ensured.")

    def record_action(self, show_id, action):
        ts = int(time.time())
        c = self.conn.cursor()
        c.execute('INSERT INTO actions (show_id, action, timestamp) VALUES (?, ?, ?)', (show_id, action, ts))
        c.execute('UPDATE shows SET last_processed=?, action=? WHERE id=?', (ts, action, show_id))
        self.conn.commit()
        logging.debug(f"Recorded action '{action}' for show_id={show_id} at {ts}.")

    def repair(self):
        # Simple integrity check
        try:
            c = self.conn.cursor()
            c.execute('PRAGMA integrity_check')
            result = c.fetchone()
            if result[0] != 'ok':
                logging.error('DB integrity check failed')
                raise Exception('DB integrity check failed')
        except Exception as e:
            logging.error(f"DB repair failed: {e}")
            return False
        logging.debug("Database integrity check passed.")
        return True

    def backup(self, backup_path):
        self.conn.commit()
        shutil.copy2(self.db_path, backup_path)
        logging.info(f"Database backed up to {backup_path}.")

    def restore(self, backup_path):
        self.conn.close()
        shutil.copy2(backup_path, self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        logging.info(f"Database restored from {backup_path}.")

    def close(self):
        if self.conn:
            self.conn.close()
            logging.debug("Database connection closed.")