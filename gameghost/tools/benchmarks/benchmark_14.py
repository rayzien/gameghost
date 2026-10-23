"""Performance benchmark tool: benchmark_14."""
import time

def run_benchmark():
    t0 = time.time()
    for _ in range(100):
        pass
    return time.time() - t0
