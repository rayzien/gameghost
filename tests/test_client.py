import unittest
from gameghost.client import calculate_letterbox

class TestGameGhostClient(unittest.TestCase):
    def test_letterbox_aspect(self):
        w, h, ox, oy = calculate_letterbox(1920, 1080, 1280, 720)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)
        self.assertEqual(ox, 0)
        self.assertEqual(oy, 0)

    def test_letterbox_pillarbox(self):
        w, h, ox, oy = calculate_letterbox(1920, 1080, 800, 600)
        self.assertLess(w, 1920)
        self.assertGreater(ox, 0)

if __name__ == "__main__":
    unittest.main()
