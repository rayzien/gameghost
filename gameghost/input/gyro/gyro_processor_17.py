"""Motion & Gyroscope processor: gyro_processor_17."""
class GyroProcessor17:
    def __init__(self, sensitivity: float = 1.0):
        self.sensitivity = sensitivity
        self.bias_x = 0.0
        self.bias_y = 0.0

    def process(self, pitch: float, yaw: float) -> tuple[float, float]:
        return (pitch - self.bias_x) * self.sensitivity, (yaw - self.bias_y) * self.sensitivity
