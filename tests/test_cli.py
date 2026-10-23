import unittest
from gameghost.cli import main

class TestGameGhostCLI(unittest.TestCase):
    def test_cli_callable(self):
        self.assertTrue(callable(main))

if __name__ == "__main__":
    unittest.main()
