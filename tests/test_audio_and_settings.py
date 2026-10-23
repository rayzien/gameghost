import os
import re
import unittest
from gameghost.launcher import GAME_ALIASES, parse_desktop_entry, GAMES_CATALOG
from gameghost.audio_server import _get_capture_command, GameAudioServer
from gameghost.client import GameGhostViewer


class TestAudioAndSettings(unittest.TestCase):
    def test_audio_capture_command_found(self):
        cmd = _get_capture_command()
        self.assertIsNotNone(cmd)
        self.assertTrue(cmd[0] in ("pw-record", "parec", "ffmpeg"))

    def test_audio_server_init(self):
        srv = GameAudioServer(port=8901)
        self.assertEqual(srv.port, 8901)
        self.assertFalse(srv.running)
        self.assertEqual(len(srv.clients), 0)

    def test_game_aliases(self):
        self.assertEqual(GAME_ALIASES.get("mk11"), "mk11")
        self.assertEqual(GAME_ALIASES.get("mortal kombat"), "mk11")
        self.assertEqual(GAME_ALIASES.get("dmc"), "dmc5")
        self.assertEqual(GAME_ALIASES.get("tekken"), "tekken8")
        self.assertEqual(GAME_ALIASES.get("sekiro"), "sekiro")
        self.assertEqual(GAME_ALIASES.get("mgr"), "mgr")
        self.assertEqual(GAME_ALIASES.get("rottr"), "rottr")

    def test_desktop_parser_space_safety(self):
        desktop_path = "/home/zero/Desktop/Mortal_Kombat_11.desktop"
        if os.path.exists(desktop_path):
            cmd, path = parse_desktop_entry(desktop_path)
            self.assertIsNotNone(cmd)
            self.assertTrue(any("MK11_DX12.exe" in part for part in cmd))

    def test_client_settings_modal_structure(self):
        viewer = GameGhostViewer(
            host_ip="127.0.0.1",
            fullscreen=False,
            preset="1080p",
            layout="xbox"
        )
        viewer.win_w = 1280
        viewer.win_h = 720
        viewer._update_layout()

        self.assertFalse(viewer.settings_open)
        self.assertIsNotNone(viewer.settings_btn)
        self.assertTrue(viewer.settings_btn.width > 0)
        self.assertIn("rect", viewer.settings_modal)
        self.assertIn("layout", viewer.settings_modal)
        self.assertIn("preset", viewer.settings_modal)
        self.assertIn("fps", viewer.settings_modal)
        self.assertIn("theme", viewer.settings_modal)
        self.assertIn("view", viewer.settings_modal)
        self.assertIn("audio", viewer.settings_modal)
        self.assertIn("games", viewer.settings_modal)
        self.assertIn("close", viewer.settings_modal)
        self.assertIn("x_close", viewer.settings_modal)

        # Toggle audio and settings
        viewer.toggle_audio()
        self.assertTrue(viewer.audio_muted)
        viewer.toggle_settings()
        self.assertTrue(viewer.settings_open)

    def test_strict_zero_emojis(self):
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\u203c-\u2049]|[\u25aa-\u25fe]'
        )
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        violations = []
        for root, dirs, files in os.walk(project_dir):
            if any(skip in root for skip in (".git", ".venv", "__pycache__")):
                continue
            for f in files:
                if f.endswith((".py", ".sh", ".md", ".json", ".toml", ".desktop")):
                    fp = os.path.join(root, f)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                            for idx, line in enumerate(file, 1):
                                if emoji_pattern.search(line):
                                    violations.append(f"{fp}:{idx}")
                    except Exception:
                        pass
        self.assertEqual(violations, [], f"Found unicode emojis in files: {violations}")


if __name__ == "__main__":
    unittest.main()
