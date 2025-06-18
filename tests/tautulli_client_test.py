import unittest
from unittest.mock import patch, MagicMock
import time
from tautulli_client import TautulliClient

class TestTautulliClient(unittest.TestCase):
    def setUp(self):
        config = {
            'tautulli': {'url': 'http://fake', 'api_key': 'key'},
            'general': {'rate_limit_tautulli': '5', 'cache_ttl_hours': '24'}
        }
        self.mock_db = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_db.conn.cursor.return_value = self.mock_cursor
        self.config = config

    @patch('tautulli_client.requests.get')
    def test_get_watch_stats_true(self, mock_get):
        # Setup mock API response with watch stats
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'response': {
                'data': [
                    {'query_days': 0, 'total_plays': 5, 'total_time': 3600}
                ]
            }
        }

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = TautulliClient(self.config, self.mock_db)
        result = client.get_watch_stats('123')

        # Test result and cache update
        self.assertTrue(result)
        self.mock_cursor.execute.assert_any_call('REPLACE INTO tautulli_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                                                ('123', 1, unittest.mock.ANY))
        self.mock_db.conn.commit.assert_called()

        # Verify API call parameters
        mock_get.assert_called_once()
        call_args = mock_get.call_args[1]
        self.assertEqual(call_args['params']['cmd'], 'get_item_watch_time_stats')
        self.assertEqual(call_args['params']['rating_key'], '123')

    @patch('tautulli_client.requests.get')
    def test_get_watch_stats_false(self, mock_get):
        # Setup mock API response with no watch stats
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'response': {
                'data': [
                    {'query_days': 0, 'total_plays': 0, 'total_time': 0}
                ]
            }
        }

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = TautulliClient(self.config, self.mock_db)
        result = client.get_watch_stats('123')

        # Test result and cache update
        self.assertFalse(result)
        self.mock_cursor.execute.assert_any_call('REPLACE INTO tautulli_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                                                ('123', 0, unittest.mock.ANY))
        self.mock_db.conn.commit.assert_called()

    @patch('tautulli_client.requests.get')
    def test_get_watch_stats_exception(self, mock_get):
        # Setup mock API to raise exception
        mock_get.side_effect = Exception('API error')

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = TautulliClient(self.config, self.mock_db)
        result = client.get_watch_stats('123')

        # Test result
        self.assertFalse(result)

    @patch('tautulli_client.requests.get')
    def test_get_watch_stats_from_cache(self, mock_get):
        # Mock DB cursor to return cached entry that isn't expired
        now = int(time.time())
        self.mock_cursor.fetchone.return_value = (1, now - 3600)  # 1 hour old cache, has_watch_history=True

        client = TautulliClient(self.config, self.mock_db)
        result = client.get_watch_stats('123')

        # Test result and verify no API call
        self.assertTrue(result)
        mock_get.assert_not_called()

    @patch('tautulli_client.requests.get')
    def test_get_watch_stats_expired_cache(self, mock_get):
        # Setup mock API response
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'response': {
                'data': [
                    {'query_days': 0, 'total_plays': 5, 'total_time': 3600}
                ]
            }
        }

        # Mock DB cursor to return cached entry that is expired
        now = int(time.time())
        cache_ttl = int(self.config['general']['cache_ttl_hours']) * 3600
        self.mock_cursor.fetchone.return_value = (0, now - cache_ttl - 3600)  # Older than cache_ttl, has_watch_history=False

        client = TautulliClient(self.config, self.mock_db)
        result = client.get_watch_stats('123')

        # Test result and verify API call was made to refresh cache
        self.assertTrue(result)
        mock_get.assert_called_once()
        self.mock_cursor.execute.assert_any_call('REPLACE INTO tautulli_cache (show_id, has_watch_history, last_checked) VALUES (?, ?, ?)',
                                                ('123', 1, unittest.mock.ANY))
        self.mock_db.conn.commit.assert_called()

if __name__ == '__main__':
    unittest.main()
