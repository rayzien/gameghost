"""Binary Protocol v2 Packet Specification: packet_type_10."""
import struct

class PacketType10:
    MAGIC = 0xAA77
    OPCODE = 0x10

    def __init__(self, seq: int = 0, timestamp: float = 0.0):
        self.seq = seq
        self.timestamp = timestamp

    def pack(self) -> bytes:
        return struct.pack("!HHI", self.MAGIC, self.OPCODE, self.seq)

    @classmethod
    def unpack(cls, data: bytes):
        magic, opcode, seq = struct.unpack("!HHI", data[:8])
        return cls(seq=seq)
