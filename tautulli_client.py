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

    def _extract_tvdb_id(self, response_json):
        """
        Extract TVDB ID from Tautulli API response
        """
        try:
            if 'response' not in response_json or 'data' not in response_json['response']:
                logging.debug("No data in Tautulli response")
                return None

            data = response_json['response']['data']

            # Direct guids in data (as in the example)
            if isinstance(data, dict) and 'guids' in data and isinstance(data['guids'], list):
                for guid in data['guids']:
                    if isinstance(guid, str) and 'tvdb' in guid.lower():
                        # Format: "tvdb://393206"
                        tvdb_id = guid.split('/')[-1]
                        if tvdb_id.isdigit():
                            logging.debug(f"Found TVDB ID {tvdb_id} in guids array")
                            return tvdb_id

            # Look in other possible locations
            if isinstance(data, dict):
                # Try to find metadata
                metadata = None
                if 'metadata' in data:
                    metadata = data['metadata']
                elif 'details' in data and 'metadata' in data['details']:
                    metadata = data['details']['metadata']

                # Search metadata if found
                if metadata:
                    # Check for guids in metadata
                    if 'guids' in metadata and isinstance(metadata['guids'], list):
                        for guid in metadata['guids']:
                            if isinstance(guid, str) and 'tvdb' in guid.lower():
                                tvdb_id = guid.split('/')[-1]
                                if tvdb_id.isdigit():
                                    return tvdb_id

                    # Check for external_ids
                    if 'external_ids' in metadata and isinstance(metadata['external_ids'], dict):
                        if 'tvdb_id' in metadata['external_ids']:
                            return str(metadata['external_ids']['tvdb_id'])

                    # Check for direct tvdbId
                    if 'tvdbId' in metadata:
                        return str(metadata['tvdbId'])

            # If data is a list of items (like history)
            if isinstance(data, list) and data:
                for item in data:
                    if isinstance(item, dict):
                        # Check for metadata in list items
                        if 'metadata' in item:
                            meta = item['metadata']
                            if 'guids' in meta and isinstance(meta['guids'], list):
                                for guid in meta['guids']:
                                    if isinstance(guid, str) and 'tvdb' in guid.lower():
                                        tvdb_id = guid.split('/')[-1]
                                        if tvdb_id.isdigit():
                                            return tvdb_id

            logging.debug(f"No TVDB ID found in Tautulli response")
            return None
        except Exception as e:
            logging.error(f"Error extracting TVDB ID: {e}")
            return None

    def _fetch_metadata(self, show_id):
        """
        Fetch full metadata for a show from Tautulli
        Returns the full metadata JSON or None if unsuccessful
        """
        self.rate_limiter.acquire()
        try:
            params = {
                'apikey': self.api_key,
                'cmd': 'get_metadata',
                'rating_key': show_id
            }
            logging.debug(f"[TautulliClient] Querying Tautulli get_metadata for show_id={show_id}")
            resp = requests.get(f"{self.url}/api/v2", params=params, timeout=10)
            logging.debug(f"[TautulliClient] Tautulli get_metadata response status: {resp.status_code}")
            resp.raise_for_status()
            metadata_json = resp.json()
            logging.debug(f"[TautulliClient] Received metadata for show_id={show_id}")
            return metadata_json
        except Exception as e:
            logging.error(f"[TautulliClient] Error fetching metadata from Tautulli for show_id={show_id}: {e}")
            return None

    def get_watch_stats(self, show_id):
        """
        Check if a show has watch history in Tautulli.
        Also extracts TVDB ID if available but doesn't save it to database.
        Returns a tuple (has_watch_history, tvdb_id) where tvdb_id may be None.
        """
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
                return bool(has_watch_history), None
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
            logging.debug(f"[TautulliClient] Querying Tautulli get_item_watch_time_stats for show_id={show_id}")
            resp = requests.get(f"{self.url}/api/v2", params=params, timeout=10)
            logging.debug(f"[TautulliClient] Tautulli get_item_watch_time_stats response status: {resp.status_code}")
            resp.raise_for_status()
            stats_json = resp.json()

            # The stats are in stats_json['response']['data']
            stats = stats_json.get('response', {}).get('data', [])
            has_watch_history = 0
            for entry in stats:
                if entry.get('total_plays', 0) > 0:
                    has_watch_history = 1
                    break

            # First try to extract TVDB ID from watch stats response
            tvdb_id = self._extract_tvdb_id(stats_json)

            # If TVDB ID not found, make a separate call to get_metadata
            if not tvdb_id:
                logging.debug(f"[TautulliClient] TVDB ID not found in watch stats, fetching full metadata")
                metadata_json = self._fetch_metadata(show_id)
                if metadata_json:
                    tvdb_id = self._extract_tvdb_id(metadata_json)

            # Found TVDB ID but don't save it to shows table yet - only log it
            if tvdb_id:
                logging.info(f"[TautulliClient] Extracted TVDB ID {tvdb_id} for show {show_id}")
                # We'll store this only for eligible shows later in the CLI
            else:
                logging.warning(f"[TautulliClient] Could not find TVDB ID for show {show_id}")

            # Store in cache
            c.execute('REPLACE INTO tautulli_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                      (show_id, has_watch_history, now))
            self.db.conn.commit()
            if has_watch_history:
                logging.info(f"[TautulliClient] Show {show_id} has watch history (total_plays > 0)")
            else:
                logging.info(f"[TautulliClient] Show {show_id} has no watch history (total_plays == 0)")
            return bool(has_watch_history), tvdb_id
        except Exception as e:
            logging.error(f"[TautulliClient] Error fetching watch stats from Tautulli for show_id={show_id}: {e}")
            return False, None