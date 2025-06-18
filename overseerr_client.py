# Handles Overseerr API integration

import time
import threading
import requests
import logging
from datetime import datetime, timedelta

# Constants
UTC_TIMEZONE_SUFFIX = '+00:00'
SQL_CACHE_INSERT = 'REPLACE INTO overseerr_cache (show_id, show_name, has_recent_request, request_date, last_checked) VALUES (?, ?, ?, ?, ?)'

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
                time.sleep((1 - self.tokens) * 60 / self.rate)
                self.tokens = 0
            else:
                self.tokens -= 1
            self.last = now

class OverseerrClient:
    def __init__(self, config, db):
        self.url = config['overseerr']['url']
        self.api_key = config['overseerr']['api_key']
        self.db = db
        self.rate_limiter = RateLimiter(int(config['general'].get('rate_limit_overseerr', 5)))
        self.threshold_days = int(config['general'].get('request_threshold_days', 365))
        self.cache_ttl = int(config['general'].get('cache_ttl_hours', 24)) * 3600  # seconds
        self.page_size = 100  # Overseerr API allows up to 100 results per page
        logging.debug(f"Initialized OverseerrClient for url '{self.url}'")

        # Ensure cache table exists
        c = self.db.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS overseerr_cache (
            show_id TEXT PRIMARY KEY,
            show_name TEXT,
            has_recent_request INTEGER,
            request_date TEXT,
            last_checked INTEGER
        )''')
        self.db.conn.commit()

        # Initialize in-memory request cache
        self.requests_cache = None
        self.requests_cache_timestamp = 0
        self.requests_cache_ttl = 3600  # 1 hour cache for requests

    def _normalize_url(self, url):
        """Normalize URL by removing trailing slash if present"""
        if url.endswith('/'):
            return url[:-1]
        return url

    def _find_working_endpoint(self, base_url, headers):
        """Find a working API endpoint for Overseerr"""
        api_endpoints = [
            f"{base_url}/api/v1/request",
            f"{base_url}/request",
        ]

        for endpoint in api_endpoints:
            try:
                test_resp = requests.get(endpoint, headers=headers, params={"take": 1}, timeout=5)
                logging.debug(f"[OverseerrClient] Testing endpoint {endpoint}: status {test_resp.status_code}")
                if test_resp.status_code == 200:
                    logging.debug(f"[OverseerrClient] Found working endpoint: {endpoint}")
                    return endpoint
            except Exception as e:
                logging.debug(f"[OverseerrClient] Error testing endpoint {endpoint}: {e}")

        logging.error("[OverseerrClient] Could not find a working API endpoint. Please check your Overseerr URL and API key.")
        return None

    def _fetch_requests_page(self, endpoint, headers, page, page_size):
        """Fetch a single page of requests from Overseerr API"""
        try:
            params = {
                "take": page_size,
                "skip": (page - 1) * page_size,
                "sort": "modified"
            }

            resp = requests.get(endpoint, headers=headers, params=params, timeout=10)
            logging.debug(f"[OverseerrClient] Response status: {resp.status_code}, URL: {resp.url}")

            if resp.status_code != 200:
                logging.error(f"[OverseerrClient] Failed to fetch requests: {resp.status_code}, message: {resp.text}")
                return None

            return resp.json()
        except Exception as e:
            logging.error(f"[OverseerrClient] Error fetching requests page {page}: {e}")
            return None

    def _extract_tv_requests(self, data):
        """Extract TV show requests from response data"""
        tv_requests = []
        if "results" in data:
            for request in data["results"]:
                # Check if it's a TV show (has tvdbId or seasons)
                media = request.get("media", {})
                if media.get("tvdbId") or "seasons" in media:
                    tv_requests.append(request)
        return tv_requests

    def _parse_date(self, date_string):
        """Parse ISO date string to datetime object, handling Z timezone"""
        if not date_string:
            return None
        return datetime.fromisoformat(date_string.replace('Z', UTC_TIMEZONE_SUFFIX))

    def _update_database_cache(self, all_requests):
        """Update database cache with request data"""
        now = int(time.time())
        try:
            c = self.db.conn.cursor()
            cache_updates = []

            for request in all_requests:
                media = request.get("media", {})
                # Use helper method to get show_id
                show_id = self._get_show_id_from_media(media)
                if not show_id:
                    continue

                show_name = media.get("name", "")
                created_at = request.get("createdAt")
                if not created_at:
                    continue

                # Use helper method to check if recent
                has_recent_request = 1 if self._is_request_recent(created_at) else 0
                request_date_str = created_at

                cache_updates.append((show_id, show_name, has_recent_request, request_date_str, now))

            if cache_updates:
                # Use executemany for batch performance
                c.executemany(SQL_CACHE_INSERT, cache_updates)
                self.db.conn.commit()
                logging.debug("[OverseerrClient] Updated database cache with {0} entries".format(len(cache_updates)))

            return True
        except Exception as e:
            logging.error("[OverseerrClient] Error updating database cache: {0}".format(str(e)))
            return False

    def _fetch_all_requests(self, force_refresh=False):
        """
        Fetches all TV show requests from the Overseerr API using pagination.
        Caches results to avoid repeated API calls.
        Populates database cache for faster lookups.
        Returns a list of TV show requests.
        """
        now = int(time.time())

        # Return cached requests if they're still fresh
        if not force_refresh and self.requests_cache is not None and (now - self.requests_cache_timestamp) < self.requests_cache_ttl:
            logging.debug("[OverseerrClient] Using cached requests ({0} items)".format(len(self.requests_cache)))
            return self.requests_cache

        # Apply rate limiting only when making actual API calls
        self.rate_limiter.acquire()

        all_requests = []
        page = 1
        total_pages = 1
        headers = {"X-Api-Key": self.api_key}

        # Use normalized URL
        base_url = self._normalize_url(self.url)
        logging.debug("[OverseerrClient] Fetching all requests")

        # Find working endpoint
        working_endpoint = self._find_working_endpoint(base_url, headers)
        if not working_endpoint:
            return []

        while page <= total_pages:
            logging.debug(f"[OverseerrClient] Fetching requests page {page} of {total_pages}")

            data = self._fetch_requests_page(working_endpoint, headers, page, self.page_size)
            if not data:
                break

            # Update total pages on first request
            if page == 1 and "pageInfo" in data:
                total_pages = data["pageInfo"]["pages"]
                logging.debug(f"[OverseerrClient] Found {total_pages} pages of requests")

            # Extract TV requests
            tv_requests = self._extract_tv_requests(data)
            all_requests.extend(tv_requests)

            page += 1

        logging.debug("[OverseerrClient] Fetched {0} TV requests from Overseerr".format(len(all_requests)))

        # Update the in-memory cache
        self.requests_cache = all_requests
        self.requests_cache_timestamp = now

        # Populate the database cache in a batch operation
        self._update_database_cache(all_requests)

        return all_requests

    def _check_db_cache(self, show_id):
        """Check if show has a recent request in the database cache"""
        now = int(time.time())
        c = self.db.conn.cursor()
        c.execute('SELECT has_recent_request, last_checked FROM overseerr_cache WHERE show_id=?', (show_id,))
        row = c.fetchone()

        if not row:
            return None

        has_recent_request, last_checked = row
        age = now - last_checked
        logging.debug(f"[OverseerrClient] DB cache hit for show_id={show_id}: has_recent_request={has_recent_request}, age={age}s")

        # Return cache hit if fresh, None if expired
        if age < self.cache_ttl:
            return bool(has_recent_request)
        else:
            logging.debug(f"[OverseerrClient] DB cache expired for show_id={show_id}")
            return None

    def _is_request_recent(self, created_at):
        """Check if a request with given date is within threshold days"""
        if not created_at:
            return False

        created_dt = datetime.fromisoformat(created_at.replace('Z', UTC_TIMEZONE_SUFFIX))
        now_dt = datetime.now(created_dt.tzinfo)

        return (now_dt - created_dt) < timedelta(days=self.threshold_days)

    def _get_show_id_from_media(self, media):
        """Extract show ID from media info"""
        return str(media.get("ratingKey") or "")

    def _process_memory_cache(self, show_id, show_name):
        """Process memory cache for a show and update database cache"""
        now = int(time.time())
        has_recent_request = 0
        most_recent_date = None

        # Find requests matching this show ID in our memory cache
        for request in self.requests_cache:
            media = request.get("media", {})
            request_show_id = self._get_show_id_from_media(media)

            if request_show_id == str(show_id):
                created_at = request.get("createdAt")
                if not created_at:
                    continue

                # Parse date for comparison
                created_dt = self._parse_date(created_at)

                # Track the most recent date
                if most_recent_date is None or created_dt > most_recent_date:
                    most_recent_date = created_dt

                # Check if request is recent
                if self._is_request_recent(created_at):
                    has_recent_request = 1
                    logging.info(f"[OverseerrClient] Show {show_id} has recent Overseerr request (within {self.threshold_days} days)")
                    break

        # Update database cache
        self._update_show_cache(show_id, show_name, has_recent_request, most_recent_date, now)
        return bool(has_recent_request)

    def _update_show_cache(self, show_id, show_name, has_recent_request, most_recent_date, timestamp):
        """Update cache for a single show"""
        request_date_str = most_recent_date.isoformat() if most_recent_date else None
        c = self.db.conn.cursor()
        c.execute(SQL_CACHE_INSERT,
                  (show_id, show_name or "", has_recent_request, request_date_str, timestamp))
        self.db.conn.commit()

    def is_recent_request(self, show_id, show_name=None):
        """
        Checks if the show with the given ID has a recent request in Overseerr.
        Uses database cache when available, or memory cache populated by _fetch_all_requests.
        """
        # Check database cache first
        result = self._check_db_cache(show_id)
        if result is not None:
            return result

        # Check if we need to refresh the memory cache
        now = int(time.time())
        if self.requests_cache is None or (now - self.requests_cache_timestamp) >= self.requests_cache_ttl:
            # Apply rate limiting only when making an API call
            self.rate_limiter.acquire()
            self._fetch_all_requests()

            # After refresh, check database again
            result = self._check_db_cache(show_id)
            if result is not None:
                return result
            return False  # Show not found in any requests after refresh

        # Use memory cache to update DB for this specific show
        try:
            return self._process_memory_cache(show_id, show_name)
        except Exception as e:
            logging.error(f"[OverseerrClient] Error in is_recent_request: {e}")
            return False