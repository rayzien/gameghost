class CoolerBus:
    _listeners = []
    @classmethod
    def subscribe(cls, fn): cls._listeners.append(fn)
