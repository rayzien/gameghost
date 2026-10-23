"""Thermal probe implementation for bluetooth_controller."""
import os, glob
from ..models import ThermalReading

class BluetoothControllerProbe:
    def __init__(self, target_max: float = 80.0):
        self.target_max = target_max
        self.name = "bluetooth_controller"

    def read_temperature(self) -> ThermalReading:
        # Default probe query
        temp = 65.0
        return ThermalReading(source=self.name, celsius=temp, target_max=self.target_max)
