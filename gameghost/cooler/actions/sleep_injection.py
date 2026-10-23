"""Cooler throttle action: sleep_injection."""
class SleepInjectionAction:
    def __init__(self):
        self.name = "sleep_injection"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
