"""Cooler throttle action: inter_frame_delay."""
class InterFrameDelayAction:
    def __init__(self):
        self.name = "inter_frame_delay"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
