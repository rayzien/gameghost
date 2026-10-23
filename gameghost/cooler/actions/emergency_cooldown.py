"""Cooler throttle action: emergency_cooldown."""
class EmergencyCooldownAction:
    def __init__(self):
        self.name = "emergency_cooldown"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
