"""Cooler throttle action: audio_buffer_relax."""
class AudioBufferRelaxAction:
    def __init__(self):
        self.name = "audio_buffer_relax"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
