# Handles Sonarr API integration

import time
import threading
import requests
import logging

# Constants
ACCEPT_JSON = 'application/json'
CONTENT_TYPE_JSON = 'application/json'

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

class SonarrClient:
    def __init__(self, config, db):
        self.url = config['sonarr']['url']
        self.api_key = config['sonarr']['api_key']
        self.db = db
        self.rate_limiter = RateLimiter(int(config['general'].get('rate_limit_sonarr', 10)))
        logging.debug(f"Initialized SonarrClient for '{self.url}'")

    def _get_series_by_tvdb_id(self, tvdb_id):
        """Get a series from Sonarr by its TVDB ID"""
        self.rate_limiter.acquire()
        try:
            headers = {
                'X-Api-Key': self.api_key,
                'Accept': ACCEPT_JSON
            }
            params = {
                'tvdbId': tvdb_id
            }

            response = requests.get(f"{self.url}/api/v3/series", headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                series_list = response.json()
                if series_list:
                    return series_list[0]  # Return the first match
                else:
                    logging.warning(f"No series found in Sonarr with TVDB ID: {tvdb_id}")
                    return None
            else:
                logging.error(f"Failed to get series from Sonarr: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logging.error(f"Error getting series from Sonarr: {e}")
            return None

    def _extract_tvdb_id_from_guid(self, guid):
        """Extract TVDB ID from Plex GUID if present"""
        if not guid:
            return None

        # Plex GUIDs have formats like:
        # com.plexapp.agents.thetvdb://121361/1/1?lang=en
        # or plex://show/5d9c086c46115600200aa2fe
        if 'thetvdb' in guid:
            try:
                # Extract the numeric ID after 'thetvdb://'
                parts = guid.split('/')
                for part in parts:
                    if part.isdigit():
                        return part
            except Exception as e:
                logging.error(f"Error extracting TVDB ID from GUID '{guid}': {e}")

        return None

    def unmonitor_series(self, show_id, guid):
        """Unmonitor a series in Sonarr by its TVDB ID extracted from Plex GUID or database"""
        # First try to get TVDB ID from the database
        tvdb_id = self.db.get_tvdb_id(show_id)

        # If not found in database, try to extract from GUID
        if not tvdb_id:
            tvdb_id = self._extract_tvdb_id_from_guid(guid)

        if not tvdb_id:
            logging.warning(f"Could not find TVDB ID for show {show_id}")
            return False

        logging.debug(f"Attempting to unmonitor series with TVDB ID: {tvdb_id}")

        # Get the series from Sonarr
        series = self._get_series_by_tvdb_id(tvdb_id)
        if not series:
            return False

        # Update the monitored status
        self.rate_limiter.acquire()
        try:
            headers = {
                'X-Api-Key': self.api_key,
                'Content-Type': CONTENT_TYPE_JSON,
                'Accept': ACCEPT_JSON
            }

            # Set monitored to false, leave other properties unchanged
            series['monitored'] = False

            response = requests.put(
                f"{self.url}/api/v3/series/{series['id']}",
                headers=headers,
                json=series,
                timeout=10
            )

            if response.status_code == 200 or response.status_code == 202:
                logging.info(f"Successfully unmonitored series {series['title']} in Sonarr")
                return True
            else:
                logging.error(f"Failed to unmonitor series in Sonarr: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Error unmonitoring series in Sonarr: {e}")
            return False

    def delete_series(self, show_id, guid, delete_files=True):
        """Delete a series from Sonarr"""
        # First try to get TVDB ID from the database
        tvdb_id = self.db.get_tvdb_id(show_id)

        # If not found in database, try to extract from GUID
        if not tvdb_id:
            tvdb_id = self._extract_tvdb_id_from_guid(guid)

        if not tvdb_id:
            logging.warning(f"Could not find TVDB ID for show {show_id}")
            return False

        logging.debug(f"Attempting to delete series with TVDB ID: {tvdb_id}")

        # Get the series from Sonarr
        series = self._get_series_by_tvdb_id(tvdb_id)
        if not series:
            return False

        # Delete the series
        self.rate_limiter.acquire()
        try:
            headers = {
                'X-Api-Key': self.api_key,
                'Accept': ACCEPT_JSON
            }

            params = {
                'deleteFiles': 'true' if delete_files else 'false'
            }

            response = requests.delete(
                f"{self.url}/api/v3/series/{series['id']}",
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                logging.info(f"Successfully deleted series {series['title']} from Sonarr")
                return True
            else:
                logging.error(f"Failed to delete series from Sonarr: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Error deleting series from Sonarr: {e}")
            return False