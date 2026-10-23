from dataclasses import dataclass

@dataclass
class CoolerConfig:
    enabled: bool = True
    interval_sec: float = 1.0
    target_temp_c: float = 78.0
    policy: str = "balanced"
    enable_fps_scaling: bool = True
    enable_resolution_scaling: bool = True
    enable_quality_scaling: bool = True
