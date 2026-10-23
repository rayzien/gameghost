PROBE_REGISTRY = {}
def register_probe(name: str, cls): PROBE_REGISTRY[name] = cls
