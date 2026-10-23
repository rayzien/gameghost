import unittest
from gameghost.discovery import GameDiscovery

class TestGameGhostDiscovery(unittest.TestCase):
    def test_discovery_init(self):
        disc = GameDiscovery(port=8990)
        self.assertEqual(disc.port, 8990)
        self.assertFalse(disc.running)

if __name__ == "__main__":
    unittest.main()
