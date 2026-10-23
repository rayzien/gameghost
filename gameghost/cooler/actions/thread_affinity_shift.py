"""Cooler throttle action: thread_affinity_shift."""
class ThreadAffinityShiftAction:
    def __init__(self):
        self.name = "thread_affinity_shift"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
