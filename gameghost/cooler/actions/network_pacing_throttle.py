"""Cooler throttle action: network_pacing_throttle."""
class NetworkPacingThrottleAction:
    def __init__(self):
        self.name = "network_pacing_throttle"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
