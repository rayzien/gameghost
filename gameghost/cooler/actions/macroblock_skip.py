"""Cooler throttle action: macroblock_skip."""
class MacroblockSkipAction:
    def __init__(self):
        self.name = "macroblock_skip"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
