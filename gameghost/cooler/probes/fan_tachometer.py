"""Thermal probe implementation for fan_tachometer."""
import os, glob
from ..models import ThermalReading

class FanTachometerProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "fan_tachometer"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
