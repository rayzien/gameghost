import unittest
from gameghost.config import (
    load_config,
    QUALITY_PRESETS,
    THEME_PRESETS,
    get_local_ip,
    get_broadcast_ip,
    log_host,
    log_client,
    HOST_LOG_FILE,
    CLIENT_LOG_FILE
)

class TestGameGhostConfig(unittest.TestCase):
    def test_quality_presets(self):
        for name in ("360p", "480p", "720p", "1080p", "1440p", "4k"):
            self.assertIn(name, QUALITY_PRESETS)
            p = QUALITY_PRESETS[name]
            self.assertIn("scale", p)
            self.assertIn("quality", p)
            self.assertIn("fps", p)

    def test_theme_presets(self):
        for name in ("cyan", "xbox", "playstation", "red", "dark"):
            self.assertIn(name, THEME_PRESETS)
            t = THEME_PRESETS[name]
            self.assertIn("border", t)
            self.assertIn("accent", t)

    def test_broadcast_ip(self):
        self.assertEqual(get_broadcast_ip("192.168.1.50"), "192.168.1.255")
        self.assertEqual(get_broadcast_ip("127.0.0.1"), "255.255.255.255")

    def test_log_helpers(self):
        log_host("Unit test host log entry")
        log_client("Unit test client log entry")
        self.assertTrue(HOST_LOG_FILE.exists())
        self.assertTrue(CLIENT_LOG_FILE.exists())

if __name__ == "__main__":
    unittest.main()
