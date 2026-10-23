def low_pass_filter(prev: float, current: float, alpha: float = 0.2) -> float:
    return alpha * current + (1.0 - alpha) * prev
