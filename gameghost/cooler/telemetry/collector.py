class TelemetryCollector:
    def __init__(self): self.samples = []
    def record(self, temp): self.samples.append(temp)
