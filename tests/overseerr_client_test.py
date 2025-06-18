import unittest
from unittest.mock import patch, MagicMock
import time
from datetime import datetime, timedelta, UTC
from overseerr_client import OverseerrClient

class TestOverseerrClient(unittest.TestCase):
    def setUp(self):
        config = {
            'overseerr': {'url': 'http://fake', 'api_key': 'key'},
            'general': {'rate_limit_overseerr': '5', 'cache_ttl_hours': '24', 'request_threshold_days': '365'}
        }
        self.mock_db = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_db.conn.cursor.return_value = self.mock_cursor
        self.config = config

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_true(self, mock_get):
        # Setup recent request date (within threshold)
        now = datetime.now(UTC)
        recent_time = (now - timedelta(days=10)).isoformat().replace('+00:00', 'Z')

        # Setup mock API response with a recent request
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'results': [
                {
                    'mediaType': 'tv',
                    'mediaInfo': {
                        'tmdbId': '123',
                        'tvdbId': '456',
                        'requests': [
                            {'createdAt': recent_time}
                        ]
                    }
                }
            ]
        }

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123', show_name='Test Show')

        # Test result and cache update
        self.assertTrue(result)
        self.mock_db.conn.commit.assert_called()

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_false(self, mock_get):
        # Setup old request date (outside threshold)
        now = datetime.now(UTC)
        threshold_days = int(self.config['general']['request_threshold_days'])
        old_time = (now - timedelta(days=threshold_days + 10)).isoformat().replace('+00:00', 'Z')

        # Setup mock API response with an old request
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'results': [
                {
                    'mediaType': 'tv',
                    'mediaInfo': {
                        'tmdbId': '123',
                        'tvdbId': '456',
                        'requests': [
                            {'createdAt': old_time}
                        ]
                    }
                }
            ]
        }

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123', show_name='Test Show')

        # Test result and cache update
        self.assertFalse(result)
        self.mock_db.conn.commit.assert_called()

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_from_cache(self, mock_get):
        # Mock DB cursor to return cached entry that isn't expired
        now = int(time.time())
        # Return: has_recent_request=1, request_date, last_checked
        self.mock_cursor.fetchone.return_value = (1, "2023-06-15T12:34:56Z", now - 3600)  # 1 hour old cache, has_recent_request=True

        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123', show_name='Test Show')

        # Test result and verify no API call
        self.assertTrue(result)
        mock_get.assert_not_called()

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_expired_cache(self, mock_get):
        # Setup recent request date
        now = datetime.now(UTC)
        recent_time = (now - timedelta(days=10)).isoformat().replace('+00:00', 'Z')

        # Setup mock API response
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'results': [
                {
                    'mediaType': 'tv',
                    'mediaInfo': {
                        'tmdbId': '123',
                        'tvdbId': '456',
                        'requests': [
                            {'createdAt': recent_time}
                        ]
                    }
                }
            ]
        }

        # Mock DB cursor to return cached entry that is expired
        now_ts = int(time.time())
        cache_ttl = int(self.config['general']['cache_ttl_hours']) * 3600
        # Return: has_recent_request=0, request_date, last_checked
        self.mock_cursor.fetchone.return_value = (0, None, now_ts - cache_ttl - 3600)  # Older than cache_ttl, has_recent_request=False

        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123', show_name='Test Show')

        # Test result and verify API call was made to refresh cache
        self.assertTrue(result)
        mock_get.assert_called_once()
        self.mock_db.conn.commit.assert_called()

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_no_show_name(self, mock_get):
        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123')  # No show_name provided

        # Test result and verify no API call
        self.assertFalse(result)
        mock_get.assert_not_called()

    @patch('overseerr_client.requests.get')
    def test_is_recent_request_api_error(self, mock_get):
        # Setup mock API to raise exception
        mock_get.side_effect = Exception('API error')

        # Setup mock DB cursor to return no cached entry
        self.mock_cursor.fetchone.return_value = None

        client = OverseerrClient(self.config, self.mock_db)
        result = client.is_recent_request('123', show_name='Test Show')

        # Test result
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
