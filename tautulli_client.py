# Handles Tautulli API integration

import time
import threading
import requests
import logging

class RateLimiter:
    def __init__(self, rate_per_minute):
        self.rate = rate_per_minute
        self.tokens = rate_per_minute
        self.last = time.time()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last
            self.tokens += elapsed * (self.rate / 60)
            if self.tokens > self.rate:
                self.tokens = self.rate
            if self.tokens < 1:
                wait_time = (1 - self.tokens) * 60 / self.rate
                logging.debug(f"[RateLimiter] Sleeping for {wait_time:.2f} seconds due to rate limiting.")
                time.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1
            self.last = now

class TautulliClient:
    def __init__(self, config, db):
        self.url = config['tautulli']['url']
        self.api_key = config['tautulli']['api_key']
        self.db = db
        self.rate_limiter = RateLimiter(int(config['general'].get('rate_limit_tautulli', 5)))
        self.cache_ttl = int(config['general'].get('cache_ttl_hours', 24)) * 3600  # seconds
        logging.debug(f"Initialized TautulliClient for url '{self.url}' with cache_ttl={self.cache_ttl}s")
        # Ensure cache table exists
        c = self.db.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tautulli_cache (
            show_id TEXT PRIMARY KEY,
            has_watch_history INTEGER,
            last_checked INTEGER
        )''')
        self.db.conn.commit()

    def get_watch_stats(self, show_id):
        # Don't rate limit for database operations
        now = int(time.time())
        c = self.db.conn.cursor()
        # Check cache
        c.execute('SELECT has_watch_history, last_checked FROM tautulli_cache WHERE show_id=?', (show_id,))
        row = c.fetchone()
        if row:
            has_watch_history, last_checked = row
            age = now - last_checked
            logging.debug(f"[TautulliClient] Cache hit for show_id={show_id}: has_watch_history={has_watch_history}, age={age}s")
            if age < self.cache_ttl:
                return bool(has_watch_history)
            else:
                logging.debug(f"[TautulliClient] Cache expired for show_id={show_id}, refreshing...")
        else:
            logging.debug(f"[TautulliClient] No cache for show_id={show_id}, querying Tautulli...")

        # Only apply rate limiting when making an actual API call
        self.rate_limiter.acquire()

        # Query Tautulli get_item_watch_time_stats
        try:
            params = {
                'apikey': self.api_key,
                'cmd': 'get_item_watch_time_stats',
                'rating_key': show_id
            }
            logging.debug(f"[TautulliClient] Querying Tautulli get_item_watch_time_stats for show_id={show_id} with params={params}")
            resp = requests.get(f"{self.url}/api/v2", params=params, timeout=10)
            logging.debug(f"[TautulliClient] Tautulli get_item_watch_time_stats response status: {resp.status_code}, response text: {resp.text}")
            resp.raise_for_status()
            stats_json = resp.json()
            logging.debug(f"[TautulliClient] Tautulli get_item_watch_time_stats response JSON: {stats_json}")
            # The stats are in stats_json['response']['data']
            stats = stats_json.get('response', {}).get('data', [])
            has_watch_history = 0
            for entry in stats:
                if entry.get('total_plays', 0) > 0:
                    has_watch_history = 1
                    break
            # Store in cache
            c.execute('REPLACE INTO tautulli_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                      (show_id, has_watch_history, now))
            self.db.conn.commit()
            if has_watch_history:
                logging.info(f"[TautulliClient] Show {show_id} has watch history (total_plays > 0)")
            else:
                logging.info(f"[TautulliClient] Show {show_id} has no watch history (total_plays == 0)")
            return bool(has_watch_history)
        except Exception as e:
            logging.error(f"[TautulliClient] Error fetching watch stats from Tautulli for show_id={show_id}: {e}")
            return False