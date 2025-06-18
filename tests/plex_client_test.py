import unittest
from unittest.mock import patch, MagicMock
from plex_client import PlexClient

class TestPlexClient(unittest.TestCase):
    def setUp(self):
        config = {
            'plex': {'url': 'http://fake', 'api_token': 'token', 'library_name': 'TV Shows'},
            'general': {'rate_limit_plex': '10', 'cache_ttl_hours': '24'}
        }
        self.mock_db = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_db.conn.cursor.return_value = self.mock_cursor
        self.config = config

    @patch('plex_client.PlexServer')
    def test_get_shows_success(self, mock_plexserver):
        mock_show1 = MagicMock()
        mock_show1.ratingKey = '101'
        mock_show1.title = 'Show1'
        mock_show1.year = 2020
        mock_show1.guid = 'plex://show1'
        mock_show2 = MagicMock()
        mock_show2.ratingKey = '102'
        mock_show2.title = 'Show2'
        mock_show2.year = 2021
        mock_show2.guid = 'plex://show2'
        mock_section = MagicMock()
        mock_section.all.return_value = [mock_show1, mock_show2]
        mock_library = MagicMock()
        mock_library.section.return_value = mock_section
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex
        client = PlexClient(self.config, self.mock_db)
        shows = client.get_shows()
        self.assertEqual(len(shows), 2)
        self.assertEqual(shows[0]['title'], 'Show1')
        self.assertEqual(shows[1]['id'], '102')

    @patch('plex_client.PlexServer')
    def test_get_shows_library_not_found(self, mock_plexserver):
        mock_library = MagicMock()
        mock_library.section.side_effect = Exception('Library not found')
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex
        client = PlexClient(self.config, self.mock_db)
        shows = client.get_shows()
        self.assertEqual(shows, [])

    @patch('plex_client.PlexServer')
    def test_delete_show_success(self, mock_plexserver):
        mock_show = MagicMock()
        mock_show.ratingKey = '101'
        mock_show.delete.return_value = None
        mock_section = MagicMock()
        mock_section.all.return_value = [mock_show]
        mock_library = MagicMock()
        mock_library.section.return_value = mock_section
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex
        client = PlexClient(self.config, self.mock_db)
        self.assertTrue(client.delete_show('101'))

    @patch('plex_client.PlexServer')
    def test_delete_show_failure(self, mock_plexserver):
        mock_show = MagicMock()
        mock_show.ratingKey = '101'
        mock_section = MagicMock()
        mock_section.all.return_value = [mock_show]
        mock_library = MagicMock()
        mock_library.section.return_value = mock_section
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex
        client = PlexClient(self.config, self.mock_db)
        self.assertFalse(client.delete_show('999'))

    @patch('plex_client.PlexServer')
    def test_has_watch_history_with_history(self, mock_plexserver):
        # Setup mock show with history
        mock_show = MagicMock()
        mock_show.ratingKey = '101'
        mock_show.history.return_value = ['watched_entry']  # Non-empty history
        mock_section = MagicMock()
        mock_section.all.return_value = [mock_show]
        mock_library = MagicMock()
        mock_library.section.return_value = mock_section
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = PlexClient(self.config, self.mock_db)
        result = client.has_watch_history('101')

        # Test result and cache update
        self.assertTrue(result)
        self.mock_cursor.execute.assert_any_call('REPLACE INTO plex_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                                                 ('101', 1, unittest.mock.ANY))
        self.mock_db.conn.commit.assert_called()

    @patch('plex_client.PlexServer')
    def test_has_watch_history_without_history(self, mock_plexserver):
        # Setup mock show without history
        mock_show = MagicMock()
        mock_show.ratingKey = '101'
        mock_show.history.return_value = []  # Empty history
        mock_section = MagicMock()
        mock_section.all.return_value = [mock_show]
        mock_library = MagicMock()
        mock_library.section.return_value = mock_section
        mock_plex = MagicMock()
        mock_plex.library = mock_library
        mock_plexserver.return_value = mock_plex

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = PlexClient(self.config, self.mock_db)
        result = client.has_watch_history('101')

        # Test result and cache update
        self.assertFalse(result)
        self.mock_cursor.execute.assert_any_call('REPLACE INTO plex_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                                                 ('101', 0, unittest.mock.ANY))
        self.mock_db.conn.commit.assert_called()

    @patch('plex_client.PlexServer')
    def test_has_watch_history_from_cache(self, mock_plexserver):
        # Mock DB cursor to return cached entry that isn't expired
        import time
        now = int(time.time())
        self.mock_cursor.fetchone.return_value = (1, now - 3600)  # 1 hour old cache, has_watch_history=True

        # We shouldn't even need to access Plex API if cache hit
        mock_plexserver.reset_mock()

        client = PlexClient(self.config, self.mock_db)
        result = client.has_watch_history('101')

        # Test result and no API calls
        self.assertTrue(result)
        # The PlexServer object should be created but no calls to section() should happen
        mock_plexserver.assert_called_once()

        # Get the mock return value and verify it wasn't used
        mock_plex = mock_plexserver.return_value
        mock_plex.library.section.assert_not_called()

if __name__ == '__main__':
    unittest.main()
