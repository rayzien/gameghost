"""Haptic feedback rumble emulator: haptic_motor_13."""
class HapticMotor13:
    def __init__(self):
        self.weak_motor = 0
        self.strong_motor = 0

    def set_vibration(self, weak: int, strong: int):
        self.weak_motor = max(0, min(65535, weak))
        self.strong_motor = max(0, min(65535, strong))
