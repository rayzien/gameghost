import unittest
from gameghost.client import calculate_letterbox, detect_controller_profile, GAMEPAD_PROFILES, GameGhostViewer

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

    def test_aspect_ratio_modes(self):
        # Stretch mode
        w, h, ox, oy = calculate_letterbox(1920, 1080, 800, 600, aspect_mode="stretch")
        self.assertEqual((w, h, ox, oy), (1920, 1080, 0, 0))

        # 16:9 mode
        w, h, ox, oy = calculate_letterbox(1920, 1080, 1920, 1080, aspect_mode="16:9")
        self.assertEqual((w, h), (1920, 1080))

        # 4:3 mode on widescreen
        w, h, ox, oy = calculate_letterbox(1920, 1080, 1920, 1080, aspect_mode="4:3")
        self.assertLess(w, 1920)
        self.assertGreater(ox, 0)

    def test_detect_controller_profile(self):
        self.assertEqual(detect_controller_profile("Sony Interactive Entertainment DualSense"), "playstation")
        self.assertEqual(detect_controller_profile("DualShock 4 Wireless Controller"), "playstation")
        self.assertEqual(detect_controller_profile("Nintendo Switch Pro Controller"), "nintendo")
        self.assertEqual(detect_controller_profile("Xbox Series X Controller"), "xbox")
        self.assertEqual(detect_controller_profile("Generic USB Joystick"), "xbox")

    def test_gamepad_profiles_exist(self):
        self.assertIn("xbox", GAMEPAD_PROFILES)
        self.assertIn("playstation", GAMEPAD_PROFILES)
        self.assertIn("nintendo", GAMEPAD_PROFILES)
        self.assertIn(0, GAMEPAD_PROFILES["xbox"])
        self.assertIn(0, GAMEPAD_PROFILES["playstation"])
        self.assertIn(0, GAMEPAD_PROFILES["nintendo"])

    def test_viewer_touch_and_mouse_customization(self):
        viewer = GameGhostViewer(host_ip="127.0.0.1")
        self.assertEqual(viewer.touch_scale, 1.0)
        self.assertEqual(viewer.touch_style, "classic")
        self.assertFalse(viewer.mouse_captured)

        # Test cycle scale
        viewer.cycle_touch_scale()
        self.assertEqual(viewer.touch_scale, 1.25)

        # Test cycle alpha
        viewer.cycle_touch_alpha()
        self.assertIn(viewer.touch_alpha, (76, 128, 190, 255))

        # Test cycle style
        viewer.cycle_touch_style()
        self.assertEqual(viewer.touch_style, "compact")

        # Test cycle aspect ratio
        viewer.cycle_aspect_ratio()
        self.assertEqual(viewer.aspect_ratio_mode, "stretch")

        # Test mouse capture toggle
        viewer.toggle_mouse_capture()
        self.assertTrue(viewer.mouse_captured)
        viewer.toggle_mouse_capture()
        self.assertFalse(viewer.mouse_captured)

if __name__ == "__main__":
    unittest.main()
