from dataclasses import dataclass
from typing import Optional

@dataclass
class ThermalReading:
    source: str
    celsius: float
    target_max: float = 80.0
    is_critical: bool = False
    timestamp: float = 0.0
