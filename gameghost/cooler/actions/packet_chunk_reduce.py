"""Cooler throttle action: packet_chunk_reduce."""
class PacketChunkReduceAction:
    def __init__(self):
        self.name = "packet_chunk_reduce"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
