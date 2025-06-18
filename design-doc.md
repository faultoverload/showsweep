# Plex-TVPurge Project Design Document

## Core Purpose
- A Python-based utility to identify and manage unwatched TV shows in Plex
- Helps users clean up their Plex library by identifying TV content that has been downloaded but never watched

## Integration with Media Services
- **Plex**: Connects to Plex server to retrieve and manage TV show libraries
- **Overseerr**: Checks if shows were requested via Overseerr before deletion
- **Tautulli**: Retrieves watch statistics to determine if shows have been watched

## Show Management Features

### Show Discovery
- Retrieves all TV shows from the configured Plex library
- Identifies completely unwatched shows (shows with no watch  or request history)
- Correlates show data across different systems using ID mapping (TVDB, TMDB, Plex IDs)

### Show Actions
- **Delete**: Remove unwatched shows completely from Plex
- **Keep first season**: Delete all but the first season of a show
- **Keep first episode**: Delete all but the first episode of a show
- **Keep**: No action, preserve the show as is

### User Interface
- Rich text console interface for displaying show information
- Interactive mode: Prompts user to choose an action for each unwatched show
- Non-interactive mode: Applies a default action to all eligible shows

## Data Management

### Local Database (SQLite)
- Caches data to reduce API calls to external services
- Stores TV show list from Plex
- Stores watch statistics from Tautulli
- Stores request data from Overseerr
- Maintains ID mappings between different services (Plex, TVDB, TMDB)
- Records processing history and actions taken

### Cache Management
- Configurable cache TTL for Plex library data (default 24 hours)
- Automatic cache refresh when data is too old
- Option to force cache refresh with `--force-refresh`

## Configuration

### Config Options
- Plex server URL, authentication token, and library name
- Overseerr API URL and API key
- Tautulli API URL and API key
- Request threshold days (how old a request must be before deletion)
- Rate limits for API calls to each service
- Default actions for non-interactive mode
- Cache expiration settings

### Configuration Sources
- INI configuration file (default at ~/.config/plex-tvpurge/config.ini)
- Command line arguments (override config file settings)
- Environment variables (e.g., for DB path and logging)
- Docker-friendly configuration (checks ./config directory)

## Operational Features

### Simulation Mode
- Default mode is simulation (doesn't actually delete files)
- Explicitly enable deletion with `--delete-files`
- Simulated actions are recorded in database with "SIM:" prefix

### Process Tracking
- Tracks actions taken on each show
- Generates processing summaries
- Records timestamps for operations

### Rate Limiting
- Implements rate limiting for API calls to external services
- Configurable rate limits per service

## Technical Features

### Error Handling
- Comprehensive error handling for API failures
- Database connection error recovery
- Safe DB transaction management

### Database Repair Utilities
- Database integrity checking
- Automatic recovery from corruption
- Backup and restore capabilities

### Logging
- Configurable logging levels (normal/debug)
- Log rotation by date
- Logs both to console and file

## Command Line Options

- `--delete-files`: Actually delete files (vs simulation mode)
- `--skip-confirmation`: Run without interactive prompts
- `--debug`: Enable debug level logging
- `--force-refresh`: Bypass cache and fetch fresh data
- `--action`: Specify default action for non-interactive mode
- Various options to override config settings (URLs, tokens, etc.)

## Additional Utilities

- Docker build file and example Docker compose file

## Safe Deletion Rules

- Shows requested through Overseerr will not be deleted if request is newer than threshold (default 1 year)
- Shows with any watch history are excluded from deletion
- Confirmation required in interactive mode before deletion