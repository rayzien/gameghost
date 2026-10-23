"""Cooler throttle action: display_brightness_drop."""
class DisplayBrightnessDropAction:
    def __init__(self):
        self.name = "display_brightness_drop"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
