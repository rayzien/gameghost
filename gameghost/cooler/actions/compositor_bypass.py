"""Cooler throttle action: compositor_bypass."""
class CompositorBypassAction:
    def __init__(self):
        self.name = "compositor_bypass"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
