import threading, time
from .config import CoolerConfig

class BaseCoolerWorker:
    def __init__(self, config: CoolerConfig = None):
        self.config = config or CoolerConfig()
        self.running = False
        self.thread = None
    def start():
        self.running = True
    def stop(self):
        self.running = False
