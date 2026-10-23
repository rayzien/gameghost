"""Cooler throttle action: process_nice_boost."""
class ProcessNiceBoostAction:
    def __init__(self):
        self.name = "process_nice_boost"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
