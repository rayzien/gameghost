"""Adaptive Jitter Buffer Module: jitter_comp_09."""
class JitterComp09:
    def __init__(self, target_ms: float = 8.0):
        self.target_ms = target_ms
        self.queue = []

    def push(self, packet):
        self.queue.append(packet)

    def pop_ready(self, now: float):
        if self.queue:
            return self.queue.pop(0)
        return None
