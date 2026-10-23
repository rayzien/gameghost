"""Cooler throttle action: gpu_clock_request."""
class GpuClockRequestAction:
    def __init__(self):
        self.name = "gpu_clock_request"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
