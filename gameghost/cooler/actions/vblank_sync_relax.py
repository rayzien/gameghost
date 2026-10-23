"""Cooler throttle action: vblank_sync_relax."""
class VblankSyncRelaxAction:
    def __init__(self):
        self.name = "vblank_sync_relax"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
