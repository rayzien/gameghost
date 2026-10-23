"""Thermal probe implementation for undervolt_monitor."""
import os, glob
from ..models import ThermalReading

class UndervoltMonitorProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "undervolt_monitor"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
