import unittest
from pathlib import Path
from gameghost.launcher import (
    GAMES_CATALOG,
    list_games,
    is_phone_environment,
    parse_desktop_exec
)

class TestGameGhostLauncher(unittest.TestCase):
    def test_catalog_structure(self):
        self.assertIn("dmc5", GAMES_CATALOG)
        self.assertIn("sekiro", GAMES_CATALOG)
        self.assertIn("tekken8", GAMES_CATALOG)
        for gid, info in GAMES_CATALOG.items():
            self.assertIn("name", info)
            self.assertIn("id", info)

    def test_list_games(self):
        catalog = list_games()
        self.assertIsInstance(catalog, dict)
        self.assertIn("dmc5", catalog)

    def test_is_phone_environment_returns_bool(self):
        res = is_phone_environment()
        self.assertIsInstance(res, bool)

    def test_parse_desktop_exec_nonexistent(self):
        self.assertIsNone(parse_desktop_exec("/nonexistent/file.desktop"))

if __name__ == "__main__":
    unittest.main()
