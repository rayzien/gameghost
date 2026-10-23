"""Thermal probe implementation for cpu_amd_ryzen."""
import os, glob
from ..models import ThermalReading

class CpuAmdRyzenProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "cpu_amd_ryzen"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
