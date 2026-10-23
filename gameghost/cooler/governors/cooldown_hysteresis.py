"""Cooling governor algorithm: cooldown_hysteresis."""
class CooldownHysteresisGovernor:
    def __init__(self, target_c: float = 78.0):
        self.target_c = target_c
        self.name = "cooldown_hysteresis"

    def compute_throttle(self, current_c: float) -> float:
        if current_c > self.target_c:
            return min(1.0, (current_c - self.target_c) / 10.0)
        return 0.0
