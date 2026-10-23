"""Cooler throttle action: fps_throttle."""
class FpsThrottleAction:
    def __init__(self):
        self.name = "fps_throttle"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
