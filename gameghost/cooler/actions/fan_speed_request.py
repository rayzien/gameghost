"""Cooler throttle action: fan_speed_request."""
class FanSpeedRequestAction:
    def __init__(self):
        self.name = "fan_speed_request"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
