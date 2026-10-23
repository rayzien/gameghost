import unittest
from gameghost.gamepad import VirtualGamepad

class TestGameGhostGamepad(unittest.TestCase):
    def test_gamepad_initialization(self):
        gp = VirtualGamepad()
        self.assertIsNotNone(gp)
        self.assertIn(gp.mode, ("gamepad", "hardware", "keyboard", "dummy", "fallback", "keyboard_fallback"))
        gp.close()

    def test_mouse_and_key_packets(self):
        gp = VirtualGamepad()
        # Ensure packet handling doesn't raise exception
        gp.handle_packet({"type": "mouse_move", "dx": 10.0, "dy": -5.0})
        gp.handle_packet({"type": "mouse_btn", "btn": "left", "val": 1})
        gp.handle_packet({"type": "mouse_btn", "btn": "left", "val": 0})
        gp.handle_packet({"type": "mouse_scroll", "dx": 0, "dy": 1})
        gp.handle_packet({"type": "key", "name": "space", "val": 1})
        gp.handle_packet({"type": "key", "name": "space", "val": 0})
        gp.handle_packet({"type": "key", "name": "w", "val": 1})
        gp.handle_packet({"type": "key", "name": "w", "val": 0})
        gp.close()

if __name__ == "__main__":
    unittest.main()
