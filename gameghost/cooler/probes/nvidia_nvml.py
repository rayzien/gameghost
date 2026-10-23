"""Thermal probe implementation for nvidia_nvml."""
import os, glob
from ..models import ThermalReading

class NvidiaNvmlProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "nvidia_nvml"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
