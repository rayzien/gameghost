"""Cooler throttle action: haptic_power_cut."""
class HapticPowerCutAction:
    def __init__(self):
        self.name = "haptic_power_cut"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
