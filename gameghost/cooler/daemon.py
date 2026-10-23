"""Base Cooler Worker Standalone Daemon Service."""
from .worker import BaseCoolerWorker

def run_cooler_daemon():
    worker = BaseCoolerWorker()
    worker.start()
