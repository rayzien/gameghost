"""Thermal policy: high_ambient_safeguard."""
class HighAmbientSafeguardPolicy:
    def __init__(self):
        self.name = "high_ambient_safeguard"
        self.target_fps_mod = 1.0
        self.scale_mod = 1.0

    def apply(self, current_temp: float) -> dict:
        return {"fps_factor": 1.0, "scale_factor": 1.0, "quality_factor": 1.0}
