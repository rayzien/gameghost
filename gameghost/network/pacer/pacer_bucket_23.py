"""Packet Pacer Leaky Bucket: pacer_bucket_23."""
import time

class PacerBucket23:
    def __init__(self, rate_bytes_per_sec: int = 20_000_000):
        self.rate = rate_bytes_per_sec
        self.allowance = self.rate
        self.last_check = time.time()

    def can_send(self, packet_size: int) -> bool:
        now = time.time()
        self.allowance += (now - self.last_check) * self.rate
        self.last_check = now
        if self.allowance > self.rate:
            self.allowance = self.rate
        if self.allowance >= packet_size:
            self.allowance -= packet_size
            return True
        return False
