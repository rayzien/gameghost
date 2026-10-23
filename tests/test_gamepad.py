import unittest
from gameghost.gamepad import VirtualGamepad

class TestGameGhostGamepad(unittest.TestCase):
    def test_gamepad_initialization(self):
        gp = VirtualGamepad()
        self.assertIsNotNone(gp)
        self.assertIn(gp.mode, ("hardware", "keyboard", "dummy", "fallback"))
        gp.close()

if __name__ == "__main__":
    unittest.main()
