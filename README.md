# ShowSweep

ShowSweep is a Python utility to identify and manage unwatched TV shows in Plex, with integration for Overseerr, Tautulli, and Sonarr. It helps you keep your TV library clean by safely removing or archiving shows that are no longer needed.

---

## 🚀 Getting Started

### 1. Clone the Repo
```sh
git clone https://github.com/faultoverload/showsweep.git
cd showsweep
```

### 2. Set Up Your Environment
- Create a virtual environment (recommended):
  ```sh
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- Or use Docker (see below)

### 3. Configure
- Copy `config/example_config.ini` to `config/config.ini` and edit it with your server URLs, API keys, and preferences.

### 4. Run ShowSweep
```sh
python main.py [options]
```

### 5. (Optional) Use Docker
```sh
docker-compose up --build
```

---

## 🛠️ Usage

- By default, ShowSweep runs in simulation mode (no files are deleted).
- Use `--skip-confirmation` and `--action` to automate actions.
- All options can be set in `config.ini` or overridden on the command line.

### Example Commands
- Interactive mode:
  ```sh
  python main.py
  ```
- Non-interactive, delete all eligible shows:
  ```sh
  python main.py --skip-confirmation --action delete
  ```
- Force refresh all data:
  ```sh
  python main.py --force-refresh
  ```
- Enable debug logging:
  ```sh
  python main.py --debug
  ```

---

## ✅ Feature Checklist

### Core Purpose
- [x] Identify and manage unwatched TV shows in Plex
- [x] Clean up Plex library by identifying TV content that has been downloaded but never watched

### Integration with Media Services
- [x] **Plex**: Retrieve and manage TV show libraries
- [x] **Overseerr**: Check if shows were requested before deletion
- [x] **Tautulli**: Retrieve watch statistics
- [x] **Sonarr**: Unmonitor or delete series as needed

### Show Management Features
- [x] Show discovery from Plex
- [x] Identify unwatched shows (no watch or request history)
- [x] Correlate show data across Plex, TVDB, TMDB
- [x] **Actions:**
  - [x] Delete: Remove unwatched shows from Plex
  - [x] Keep first season: Delete all but the first season
  - [x] Keep first episode: Delete all but the first episode
  - [x] Keep: No action

### User Interface
- [x] Rich text console interface
- [x] Interactive mode: Prompt for each show
- [x] Non-interactive mode: Apply default action

### Data Management
- [x] Local SQLite database for caching and tracking
- [x] Store TV show list, watch stats, request data, and ID mappings
- [x] Record processing history and actions

### Cache Management
- [x] Configurable cache TTL (default 24h)
- [x] Automatic cache refresh
- [x] Force refresh option

### Configuration
- [x] All options in `config.ini`
- [x] Command line overrides
- [x] Environment variable support
- [x] Docker-friendly config

### Operational Features
- [x] Simulation mode (no files deleted by default)
- [x] Explicit deletion with `--action delete`
- [x] Processing summaries and logs
- [x] Tracks actions and timestamps

### Rate Limiting
- [x] Configurable per-service rate limits

### Technical Features
- [x] Error handling for API/database failures
- [x] Safe DB transaction management
- [x] Database repair, backup, and restore
- [x] Configurable logging (console and file)

### Command Line Options
- [x] `--skip-confirmation`: Non-interactive mode
- [x] `--debug`: Debug logging
- [x] `--force-refresh`: Bypass cache
- [x] `--action`: Default action for eligible shows
- [x] `--skip-overseerr`, `--skip-tautulli`: Skip checks
- [x] `--ignore-first-season`, `--ignore-first-episode`: Ignore certain shows

### Safe Deletion Rules
- [x] Do not delete shows with recent Overseerr requests
- [x] Do not delete shows with any watch history
- [x] Confirmation required in interactive mode

---

## Configuration

- See `config/example_config.ini` for all available options and documentation.
- Place your config as `config/config.ini` or set the `SHOWSWEEP_CONFIG` environment variable.

---

## Contributing
Pull requests and issues are welcome!

---

## License
MIT
