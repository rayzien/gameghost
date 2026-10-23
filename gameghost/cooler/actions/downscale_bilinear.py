"""Cooler throttle action: downscale_bilinear."""
class DownscaleBilinearAction:
    def __init__(self):
        self.name = "downscale_bilinear"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
