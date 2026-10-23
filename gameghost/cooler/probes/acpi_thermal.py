"""Thermal probe implementation for acpi_thermal."""
import os, glob
from ..models import ThermalReading

class AcpiThermalProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "acpi_thermal"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
