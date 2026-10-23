"""Cooler throttle action: jpeg_quality_stepper."""
class JpegQualityStepperAction:
    def __init__(self):
        self.name = "jpeg_quality_stepper"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
