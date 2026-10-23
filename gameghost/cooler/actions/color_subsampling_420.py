"""Cooler throttle action: color_subsampling_420."""
class ColorSubsampling420Action:
    def __init__(self):
        self.name = "color_subsampling_420"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
