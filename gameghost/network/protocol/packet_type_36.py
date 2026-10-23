"""Binary Protocol v2 Packet Specification: packet_type_36."""
import struct

class PacketType36:
    MAGIC = 0xAA77
    OPCODE = 0x36

    def __init__(self, seq: int = 0, timestamp: float = 0.0):
        self.seq = seq
        self.timestamp = timestamp

    def pack(self) -> bytes:
        return struct.pack("!HHI", self.MAGIC, self.OPCODE, self.seq)

    @classmethod
    def unpack(cls, data: bytes):
        magic, opcode, seq = struct.unpack("!HHI", data[:8])
        return cls(seq=seq)
