class CoolerContext:
    def __init__(self):
        self.active_policy = "balanced"
        self.current_temp = 0.0
        self.last_action = None
