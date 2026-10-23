import threading, time
class CoolerScheduler:
    def __init__(self, interval, fn):
        self.interval = interval
        self.fn = fn
