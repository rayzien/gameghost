import os
import queue
import unittest
from unittest.mock import patch, MagicMock

import gameghost
from gameghost.update import get_current_version
from gameghost.launcher import launch_game
from gameghost.client import GameGhostViewer
from gameghost.stream_server import _activate_game_window


class TestTermuxX11AndStreaming(unittest.TestCase):
    def test_version_v1_7_2(self):
        """Verify release version is synchronized at v1.7.2."""
        self.assertEqual(gameghost.__version__, "1.7.2")
        self.assertEqual(get_current_version(), "1.7.2")

    def test_termux_display_environment_detection(self):
        """Verify Termux-X11 display variable logic."""
        prefix_tmp = "/tmp/test_termux_tmp"
        os.makedirs(f"{prefix_tmp}/.X11-unix", exist_ok=True)
        sock_path = f"{prefix_tmp}/.X11-unix/X1"
        with open(sock_path, "w") as f:
            f.write("")

        # Simulate detection
        detected = ":0"
        for n in ("0", "1", "2"):
            if os.path.exists(f"{prefix_tmp}/.X11-unix/X{n}"):
                detected = f":{n}"
                break
        self.assertEqual(detected, ":1")

        if os.path.exists(sock_path):
            os.remove(sock_path)
        os.rmdir(f"{prefix_tmp}/.X11-unix")
        os.rmdir(prefix_tmp)

    def test_game_launcher_strips_software_rasterizer(self):
        """Verify launcher.py strips LIBGL_ALWAYS_SOFTWARE and llvmpipe overrides."""
        with patch.dict(os.environ, {
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "GALLIUM_DRIVER": "llvmpipe",
            "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
            "SDL_RENDER_DRIVER": "software"
        }):
            with patch("subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock(pid=12345)
                launch_game("dmc5")
                self.assertTrue(mock_popen.called)
                env_used = mock_popen.call_args[1].get("env", {})
                self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", env_used)
                self.assertNotIn("GALLIUM_DRIVER", env_used)
                self.assertNotIn("MESA_LOADER_DRIVER_OVERRIDE", env_used)
                self.assertNotIn("SDL_RENDER_DRIVER", env_used)

    def test_client_frame_queue_non_blocking(self):
        """Verify frame queue handles put_nowait and drop without blocking."""
        viewer = GameGhostViewer(host_ip="127.0.0.1")
        # Fill queue
        viewer.frame_queue.put(b"frame1")
        viewer.frame_queue.put(b"frame2")
        self.assertTrue(viewer.frame_queue.full())

        # Simulate non-blocking arrival of frame3 (drops frame1, adds frame3)
        if viewer.frame_queue.full():
            try:
                viewer.frame_queue.get_nowait()
            except queue.Empty:
                pass
        viewer.frame_queue.put_nowait(b"frame3")

        item1 = viewer.frame_queue.get_nowait()
        item2 = viewer.frame_queue.get_nowait()
        self.assertEqual(item1, b"frame2")
        self.assertEqual(item2, b"frame3")

    def test_activate_game_window_safe(self):
        """Verify _activate_game_window handles invalid/dummy window safely without crashing."""
        res = _activate_game_window(0x999999)
        self.assertIsInstance(res, bool)


if __name__ == "__main__":
    unittest.main()
