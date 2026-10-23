class ThermalRingBuffer:
    def __init__(self, capacity: int = 120):
        self.capacity = capacity
        self.buffer = []
    def append(self, val: float):
        if len(self.buffer) >= self.capacity:
            self.buffer.pop(0)
        self.buffer.append(val)
    def average(self) -> float:
        return sum(self.buffer) / max(1, len(self.buffer))
