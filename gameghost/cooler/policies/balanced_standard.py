"""Thermal policy: balanced_standard."""
class BalancedStandardPolicy:
    def __init__(self):
        self.name = "balanced_standard"
        self.target_fps_mod = 1.0
        self.scale_mod = 1.0

    def apply(self, current_temp: float) -> dict:
        return {"fps_factor": 1.0, "scale_factor": 1.0, "quality_factor": 1.0}
