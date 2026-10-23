"""Cooler throttle action: stream_pause_burst."""
class StreamPauseBurstAction:
    def __init__(self):
        self.name = "stream_pause_burst"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
