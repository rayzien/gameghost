class ActionDispatcher:
    def __init__(self):
        self.handlers = []
    def register(self, h): self.handlers.append(h)
