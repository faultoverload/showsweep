import argparse
import sys
import logging
import time
from plex_client import PlexClient
from overseerr_client import OverseerrClient
from tautulli_client import TautulliClient
from sonarr_client import SonarrClient

# Handles command line interface and argument parsing

def main_cli(config, db):
    # Helper to get config value with type
    def get_config_bool(section, key, default=False):
        if section not in config:
            return default
        if key not in config[section]:
            return default
        val = config[section][key]
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("1", "true", "yes", "on")
    def get_config_str(section, key, default=None):
        if section not in config:
            return default
        if key not in config[section]:
            return default
        return config[section][key]

    parser = argparse.ArgumentParser(description="ShowSweep: Manage unwatched TV shows in Plex.")
    parser.add_argument('--skip-confirmation', action='store_true', default=get_config_bool('general', 'skip_confirmation', False), help='Run without interactive prompts')
    parser.add_argument('--debug', action='store_true', default=get_config_bool('general', 'debug', False), help='Enable debug level logging')
    parser.add_argument('--force-refresh', action='store_true', default=get_config_bool('general', 'force_refresh', False), help='Bypass cache and fetch fresh data')
    parser.add_argument('--action', choices=['delete', 'keep_first_season', 'keep_first_episode', 'keep'], default=get_config_str('general', 'action', None), help='Default action for non-interactive mode')
    parser.add_argument('--skip-overseerr', action='store_true', default=get_config_bool('general', 'skip_overseerr', False), help='Skip Overseerr checks for recent requests')
    parser.add_argument('--skip-tautulli', action='store_true', default=get_config_bool('general', 'skip_tautulli', False), help='Skip Tautulli checks for watch history')
    parser.add_argument('--ignore-first-season', action='store_true', default=get_config_bool('general', 'ignore_first_season', False), help='Ignore shows that only have their first season downloaded')
    parser.add_argument('--ignore-first-episode', action='store_true', default=get_config_bool('general', 'ignore_first_episode', False), help='Ignore shows that only have their first episode downloaded')
    args = parser.parse_args()

    # Set logging level to DEBUG if --debug is passed
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Debug mode enabled via --debug argument.")

    logging.debug(f"CLI arguments: {args}")
    # Initialize API clients
    plex = PlexClient(config, db)
    overseerr = OverseerrClient(config, db)
    tautulli = TautulliClient(config, db)
    sonarr = SonarrClient(config, db)
    logging.debug("Initialized Plex, Overseerr, Tautulli, and Sonarr clients.")

    # Prefetch all Overseerr requests only if we're not skipping Overseerr checks
    if not args.skip_overseerr:
        logging.info("Prefetching Overseerr requests...")
        overseerr._fetch_all_requests(force_refresh=args.force_refresh)
        logging.info("Overseerr requests cached.")
    else:
        logging.info("Skipping Overseerr prefetch (--skip-overseerr enabled)")

    # Keep track of eligible shows for final report
    eligible_shows = []
    total_shows = 0
    skipped_shows = {'overseerr': 0, 'tautulli': 0, 'plex': 0}

    # Main logic: discover shows, apply rules, prompt user or apply default action
    shows = plex.get_shows()
    total_shows = len(shows)
    logging.info(f"Discovered {total_shows} shows from Plex.")

    for show in shows:
        logging.debug(f"Processing show: {show}")

        # Check if the show has only first season or first episode
        has_only_first_season = show.get('has_only_first_season', False)
        has_only_first_episode = show.get('has_only_first_episode', False)

        # Skip shows with only first season if ignore-first-season is set
        if args.ignore_first_season and has_only_first_season:
            logging.info(f"Ignoring show '{show['title']}' (has only first season)")
            continue

        # Skip shows with only first episode if ignore-first-episode is set
        if args.ignore_first_episode and has_only_first_episode:
            logging.info(f"Ignoring show '{show['title']}' (has only first episode)")
            continue

        # Check safe deletion rules (respecting skip arguments)
        if not args.skip_overseerr and overseerr.is_recent_request(show['id']):
            logging.info(f"Skipping show '{show['title']}' (recent Overseerr request)")
            skipped_shows['overseerr'] += 1
            continue

        # Get watch stats and possibly TVDB ID from Tautulli
        if not args.skip_tautulli:
            has_watch_history, tvdb_temp = tautulli.get_watch_stats(show['id'])
            if has_watch_history:
                logging.info(f"Skipping show '{show['title']}' (has watch history in Tautulli)")
                skipped_shows['tautulli'] += 1
                continue
            # We'll save tvdb_temp later if the show is eligible

        if plex.has_watch_history(show['id']):
            logging.info(f"Skipping show '{show['title']}' (has watch history in Plex)")
            skipped_shows['plex'] += 1
            continue

        # Show is eligible for action
        logging.debug(f"Show '{show['title']}' eligible for action.")

        # Use TVDB ID from Tautulli if available, otherwise fetch it
        tvdb_id = tvdb_temp if 'tvdb_temp' in locals() and tvdb_temp else None

        if not tvdb_id and not args.skip_tautulli:
            # Only fetch metadata if we didn't already get TVDB ID from get_watch_stats
            metadata_json = tautulli._fetch_metadata(show['id'])
            if metadata_json:
                tvdb_id = tautulli._extract_tvdb_id(metadata_json)

        # Save TVDB ID for eligible show
        if tvdb_id:
            logging.info(f"Found TVDB ID {tvdb_id} for eligible show '{show['title']}'")
            db.save_tvdb_id(show['id'], tvdb_id)

        # Add TVDB ID to the show object if we have it
        if tvdb_id:
            show['tvdb_id'] = tvdb_id

        eligible_shows.append(show)

        # Insert or update eligible show in the shows table
        c = db.conn.cursor()
        now = int(time.time())
        if tvdb_id:
            c.execute('REPLACE INTO shows (id, title, last_processed, action, tvdb_id) VALUES (?, ?, ?, ?, ?)',
                     (show['id'], show['title'], now, 'eligible', tvdb_id))
        else:
            c.execute('REPLACE INTO shows (id, title, last_processed, action) VALUES (?, ?, ?, ?)',
                     (show['id'], show['title'], now, 'eligible'))
    db.conn.commit()
    logging.debug(f"Recorded {len(eligible_shows)} eligible shows in the database.")

    # Generate summary report
    eligible_count = len(eligible_shows)
    logging.info("=" * 50)
    logging.info("SHOWSWEEP REPORT")
    logging.info("=" * 50)
    logging.info(f"Total shows scanned: {total_shows}")
    logging.info(f"Shows skipped due to Overseerr recent requests: {skipped_shows['overseerr']}")
    logging.info(f"Shows skipped due to Tautulli watch history: {skipped_shows['tautulli']}")
    logging.info(f"Shows skipped due to Plex watch history: {skipped_shows['plex']}")
    logging.info(f"Shows eligible for action: {eligible_count}")

    if eligible_count > 0:
        logging.info("\nEligible shows:")
        logging.info("-" * 50)
        for i, show in enumerate(eligible_shows, 1):
            year = f" ({show['year']})" if show.get('year') else ""
            logging.info(f"{i}. {show['title']}{year}")

        if args.skip_confirmation:
            # Non-interactive: apply the action flag to all eligible shows
            action = args.action or 'keep'
            logging.info(f"Applying action '{action}' to all eligible shows (skip-confirmation enabled)")
            for show in eligible_shows:
                if action == 'delete':
                    # Delete show in Plex
                    if plex.delete_show(show['id']):
                        logging.info(f"Deleted show '{show['title']}' from Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                elif action == 'keep_first_season':
                    # Keep only first season in Plex
                    if plex.keep_first_season(show['id']):
                        logging.info(f"Kept only first season of '{show['title']}' in Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                elif action == 'keep_first_episode':
                    # Keep only first episode in Plex
                    if plex.keep_first_episode(show['id']):
                        logging.info(f"Kept only first episode of '{show['title']}' in Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                else:  # keep
                    logging.info(f"Keeping show '{show['title']}' as is")

                db.record_action(show['id'], action)
                logging.info(f"Action '{action}' applied to show: {show['title']}")
        else:
            # Interactive: prompt user for each eligible show
            for show in eligible_shows:
                print(f"\nShow: {show['title']} ({show.get('year', '')})")
                print("Choose action:")
                print("  1. delete")
                print("  2. keep_first_season")
                print("  3. keep_first_episode")
                print("  4. keep")
                choice = input("Enter choice [1-4, default=4]: ").strip()
                if choice == '1':
                    action = 'delete'
                    # Delete show in Plex
                    if plex.delete_show(show['id']):
                        logging.info(f"Deleted show '{show['title']}' from Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                elif choice == '2':
                    action = 'keep_first_season'
                    # Keep only first season in Plex
                    if plex.keep_first_season(show['id']):
                        logging.info(f"Kept only first season of '{show['title']}' in Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                elif choice == '3':
                    action = 'keep_first_episode'
                    # Keep only first episode in Plex
                    if plex.keep_first_episode(show['id']):
                        logging.info(f"Kept only first episode of '{show['title']}' in Plex")
                    # Unmonitor in Sonarr
                    if sonarr.unmonitor_series(show['id'], show.get('guid')):
                        logging.info(f"Unmonitored show '{show['title']}' in Sonarr")
                else:
                    action = 'keep'
                    logging.info(f"Keeping show '{show['title']}' as is")
                db.record_action(show['id'], action)
                logging.info(f"Action '{action}' applied to show: {show['title']}")

    logging.info("\nProcessing complete.")