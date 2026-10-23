"""Cooler throttle action: frame_dropper."""
class FrameDropperAction:
    def __init__(self):
        self.name = "frame_dropper"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
