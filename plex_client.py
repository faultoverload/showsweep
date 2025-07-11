# Handles Plex API integration

import time
import threading
from plexapi.server import PlexServer
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
                time.sleep((1 - self.tokens) * 60 / self.rate)
                self.tokens = 0
            else:
                self.tokens -= 1
            self.last = now

class PlexClient:
    def __init__(self, config, db):
        self.url = config['plex']['url']
        self.token = config['plex']['api_token']
        self.library = config['plex']['library_name']
        self.db = db
        self.rate_limiter = RateLimiter(int(config['general'].get('rate_limit_plex', 10)))
        self.cache_ttl = int(config['general'].get('cache_ttl_hours', 24)) * 3600  # seconds
        self.plex = PlexServer(self.url, self.token)
        logging.debug(f"Initialized PlexClient for library '{self.library}' at '{self.url}'")
        # Ensure cache table exists
        c = self.db.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS plex_cache (
            show_id TEXT PRIMARY KEY,
            has_watch_history INTEGER,
            last_checked INTEGER
        )''')
        self.db.conn.commit()

    def get_shows(self):
        self.rate_limiter.acquire()
        try:
            logging.debug(f"Fetching shows from Plex library '{self.library}'")
            section = self.plex.library.section(self.library)
            shows = section.all()
            result = []
            for show in shows:
                logging.debug(f"Found show: {show.title} (ratingKey={show.ratingKey})")

                # Check if show has only first season
                has_only_first_season = False
                # Check if show has only one episode
                has_only_first_episode = False

                try:
                    # Get seasons for this show with timeout
                    seasons = show.seasons()
                    season_count = len(seasons)

                    # Check if only season 1 exists
                    if season_count == 1 and seasons[0].index == 1:
                        has_only_first_season = True
                        logging.debug(f"Show {show.title} has only first season")

                    # Use more efficient episode count checking
                    total_episodes = 0
                    if season_count == 1:  # Only check episode count for potential single-episode shows
                        # Add timeout handling for episode fetching
                        try:
                            episodes = seasons[0].episodes()
                            total_episodes = len(episodes)
                            if total_episodes == 1:
                                has_only_first_episode = True
                                logging.debug(f"Show {show.title} has only one episode")
                        except Exception as e_ep:
                            logging.error(f"Error checking episodes for {show.title}: {e_ep}")
                except Exception as e:
                    logging.error(f"Error checking seasons/episodes for {show.title}: {e}")

                # Create show object
                show_obj = {
                    'id': show.ratingKey,
                    'title': show.title,
                    'year': getattr(show, 'year', None),
                    'guid': getattr(show, 'guid', None),
                    'has_only_first_season': has_only_first_season,
                    'has_only_first_episode': has_only_first_episode
                }

                # Calculate disk space for the show (deferred to be calculated on demand)
                result.append(show_obj)
            return result
        except Exception as e:
            logging.error(f"Error fetching shows from Plex: {e}")
            return []

    def delete_show(self, show_id):
        self.rate_limiter.acquire()
        try:
            logging.debug(f"Attempting to delete show with ratingKey={show_id}")
            section = self.plex.library.section(self.library)
            show = next((s for s in section.all() if str(s.ratingKey) == str(show_id)), None)
            if show:
                show.delete()
                logging.info(f"Deleted show with ratingKey={show_id}")
                return True
            logging.warning(f"Show with ratingKey={show_id} not found for deletion")
            return False
        except Exception as e:
            logging.error(f"Error deleting show {show_id} from Plex: {e}")
            return False

    def has_watch_history(self, show_id):
        """
        Returns True if the show with the given ratingKey has any play history in Plex.
        Caches results in the database to reduce API calls.
        """
        # Don't rate limit for database operations
        now = int(time.time())
        c = self.db.conn.cursor()

        # Check cache first
        c.execute('SELECT has_watch_history, last_checked FROM plex_cache WHERE show_id=?', (show_id,))
        row = c.fetchone()
        if row:
            has_watch_history, last_checked = row
            age = now - last_checked
            logging.debug(f"[PlexClient] Cache hit for show_id={show_id}: has_watch_history={has_watch_history}, age={age}s")
            if age < self.cache_ttl:
                return bool(has_watch_history)
            else:
                logging.debug(f"[PlexClient] Cache expired for show_id={show_id}, refreshing...")
        else:
            logging.debug(f"[PlexClient] No cache for show_id={show_id}, checking Plex...")

        # Only apply rate limiting when making an actual API call
        self.rate_limiter.acquire()

        # Query Plex if cache miss or expired
        try:
            section = self.plex.library.section(self.library)
            show = next((s for s in section.all() if str(s.ratingKey) == str(show_id)), None)
            if not show:
                logging.debug(f"[PlexClient] Show with ratingKey={show_id} not found in Plex library for history check.")
                # Cache the negative result
                c.execute('REPLACE INTO plex_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                          (show_id, 0, now))
                self.db.conn.commit()
                return False

            history = show.history()
            logging.debug(f"[PlexClient] Plex play history for show_id={show_id}: {history}")
            has_watch_history = 1 if history else 0

            # Cache the result
            c.execute('REPLACE INTO plex_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                      (show_id, has_watch_history, now))
            self.db.conn.commit()

            if has_watch_history:
                logging.info(f"[PlexClient] Show {show_id} has watch history in Plex")
            else:
                logging.info(f"[PlexClient] Show {show_id} has no watch history in Plex")

            return bool(has_watch_history)
        except Exception as e:
            logging.error(f"[PlexClient] Error checking Plex play history for show_id={show_id}: {e}")
            return False

    def keep_first_season(self, show_id):
        """
        Keep only the first season of a show, delete all other seasons
        """
        self.rate_limiter.acquire()
        try:
            logging.info(f"Keeping only the first season for show with ratingKey={show_id}")
            section = self.plex.library.section(self.library)
            show = next((s for s in section.all() if str(s.ratingKey) == str(show_id)), None)
            if not show:
                logging.warning(f"Show with ratingKey={show_id} not found")
                return False

            # Get all seasons
            seasons = show.seasons()
            if not seasons:
                logging.warning(f"No seasons found for show {show.title}")
                return False

            # Sort seasons by index
            seasons.sort(key=lambda s: s.index)

            # Keep first season, delete the rest
            kept_season = seasons[0]
            seasons_deleted = 0

            for season in seasons:
                if season.index != kept_season.index:
                    logging.info(f"Deleting season {season.index} of {show.title}")
                    try:
                        season.delete()
                        seasons_deleted += 1
                    except Exception as e:
                        logging.error(f"Error deleting season {season.index} of {show.title}: {e}")

            if seasons_deleted > 0:
                logging.info(f"Kept season {kept_season.index} and deleted {seasons_deleted} other seasons of {show.title}")
                return True
            else:
                logging.info(f"Only one season exists for {show.title}, nothing to delete")
                return True
        except Exception as e:
            logging.error(f"Error keeping first season for show {show_id}: {e}")
            return False

    def keep_first_episode(self, show_id):
        """
        Keep only the first episode of a show, delete all other episodes and seasons
        """
        self.rate_limiter.acquire()
        try:
            logging.info(f"Keeping only the first episode for show with ratingKey={show_id}")
            section = self.plex.library.section(self.library)
            show = next((s for s in section.all() if str(s.ratingKey) == str(show_id)), None)
            if not show:
                logging.warning(f"Show with ratingKey={show_id} not found")
                return False

            # Get all seasons
            seasons = show.seasons()
            if not seasons:
                logging.warning(f"No seasons found for show {show.title}")
                return False

            # Sort seasons by index
            seasons.sort(key=lambda s: s.index)

            # Get episodes from first season
            first_season = seasons[0]
            episodes = first_season.episodes()

            if not episodes:
                logging.warning(f"No episodes found in first season of {show.title}")
                return False

            # Sort episodes by index
            episodes.sort(key=lambda e: e.index)

            # Keep first episode, delete the rest
            kept_episode = episodes[0]
            episodes_deleted = 0

            # Delete other episodes in first season
            for episode in episodes:
                if episode.index != kept_episode.index:
                    logging.info(f"Deleting episode {episode.index} of season {first_season.index} of {show.title}")
                    try:
                        episode.delete()
                        episodes_deleted += 1
                    except Exception as e:
                        logging.error(f"Error deleting episode {episode.index} of season {first_season.index} of {show.title}: {e}")

            # Delete all other seasons
            for season in seasons:
                if season.index != first_season.index:
                    logging.info(f"Deleting season {season.index} of {show.title}")
                    try:
                        season.delete()
                        # Don't count individual episodes for other seasons
                    except Exception as e:
                        logging.error(f"Error deleting season {season.index} of {show.title}: {e}")

            logging.info(f"Kept episode {kept_episode.index} of season {first_season.index} and deleted {episodes_deleted} other episodes/seasons of {show.title}")
            return True
        except Exception as e:
            logging.error(f"Error keeping first episode for show {show_id}: {e}")
            return False

    def get_show_disk_space(self, show_id):
        """
        Calculate the total disk space used by a show in bytes
        Returns a tuple of (total_size, formatted_size)
        """
        self.rate_limiter.acquire()
        try:
            logging.debug(f"Calculating disk space for show with ratingKey={show_id}")
            section = self.plex.library.section(self.library)
            show = next((s for s in section.all() if str(s.ratingKey) == str(show_id)), None)
            if not show:
                logging.warning(f"Show with ratingKey={show_id} not found for disk space calculation")
                return 0, "0 MB"

            total_size = 0

            # Get all episodes for this show
            for episode in show.episodes():
                # Each episode can have multiple media versions (different qualities, formats)
                for media in episode.media:
                    # Each media can have multiple parts (files)
                    for part in media.parts:
                        # Add the file size
                        if hasattr(part, 'size') and part.size:
                            total_size += part.size

            # Format the size for display
            formatted_size = self._format_size(total_size)
            logging.debug(f"Show {show.title} uses {formatted_size} of disk space")
            return total_size, formatted_size
        except Exception as e:
            logging.error(f"Error calculating disk space for show {show_id}: {e}")
            return 0, "0 MB"

    def _format_size(self, size_bytes):
        """Format bytes into human-readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / (1024 ** 2):.1f} MB"
        elif size_bytes < 1024 ** 4:
            return f"{size_bytes / (1024 ** 3):.1f} GB"
        else:
            return f"{size_bytes / (1024 ** 4):.1f} TB"