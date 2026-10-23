from enum import Enum

class ThermalState(Enum):
    NORMAL = "normal"
    WARM = "warm"
    HOT = "hot"
    CRITICAL = "critical"
    EMERGENCY = "emergency"
