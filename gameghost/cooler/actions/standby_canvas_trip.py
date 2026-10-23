"""Cooler throttle action: standby_canvas_trip."""
class StandbyCanvasTripAction:
    def __init__(self):
        self.name = "standby_canvas_trip"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
