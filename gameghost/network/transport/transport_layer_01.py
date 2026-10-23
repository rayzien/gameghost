"""Network Transport Optimization: transport_layer_01."""
import socket

class TransportLayer01:
    def configure_socket(self, sock: socket.socket):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            # DSCP CS4 priority
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0x88)
        except Exception:
            pass
