"""Response curve profile: curve_profile_22."""
class CurveProfile22:
    def __init__(self, exponent: float = 1.8):
        self.exponent = exponent

    def transform(self, val: float) -> float:
        sign = 1.0 if val >= 0 else -1.0
        return sign * (abs(val) ** self.exponent)
