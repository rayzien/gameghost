"""Forward Error Correction Block: fec_block_28."""
class FecBlock28:
    def __init__(self, k: int = 10, m: int = 2):
        self.k = k
        self.m = m

    def encode(self, shards: list) -> list:
        parity = bytearray(len(shards[0]))
        for s in shards:
            for i, b in enumerate(s):
                parity[i] ^= b
        return [bytes(parity)]
