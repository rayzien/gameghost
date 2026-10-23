"""Kalman Filter Latency Estimator: kalman_filter_29."""
class KalmanFilter29:
    def __init__(self, q: float = 0.001, r: float = 0.1):
        self.q = q
        self.r = r
        self.x = 0.0
        self.p = 1.0

    def update(self, measurement: float) -> float:
        self.p += self.q
        k_gain = self.p / (self.p + self.r)
        self.x += k_gain * (measurement - self.x)
        self.p *= (1.0 - k_gain)
        return self.x
