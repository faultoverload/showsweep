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
            last_modified INTEGER,
            last_processed INTEGER,
            tvdb_id TEXT,
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
        """
        Record an action taken for a show
        """
        try:
            c = self.conn.cursor()
            now = int(time.time())
            c.execute('UPDATE shows SET action = ?, last_modified = ? WHERE id = ?',
                     (action, now, show_id))
            self.conn.commit()
            return True
        except Exception as e:
            logging.error(f"Error recording action {action} for show {show_id}: {e}")
            return False

    def save_tvdb_id(self, show_id, tvdb_id):
        """
        Store the TVDB ID for a show
        """
        try:
            c = self.conn.cursor()
            c.execute('UPDATE shows SET tvdb_id = ? WHERE id = ?', (tvdb_id, show_id))
            # If show doesn't exist yet, insert it
            if c.rowcount == 0:
                c.execute('INSERT OR IGNORE INTO shows (id, tvdb_id) VALUES (?, ?)', (show_id, tvdb_id))
            self.conn.commit()
            return True
        except Exception as e:
            logging.error(f"Error saving TVDB ID {tvdb_id} for show {show_id}: {e}")
            return False

    def get_tvdb_id(self, show_id):
        """
        Retrieve the TVDB ID for a show
        """
        try:
            c = self.conn.cursor()
            c.execute('SELECT tvdb_id FROM shows WHERE id = ?', (show_id,))
            result = c.fetchone()
            return result[0] if result else None
        except Exception as e:
            logging.error(f"Error retrieving TVDB ID for show {show_id}: {e}")
            return None

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