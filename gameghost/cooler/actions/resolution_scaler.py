"""Cooler throttle action: resolution_scaler."""
class ResolutionScalerAction:
    def __init__(self):
        self.name = "resolution_scaler"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
