"""Cooler throttle action: encoder_preset_shift."""
class EncoderPresetShiftAction:
    def __init__(self):
        self.name = "encoder_preset_shift"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
