import asyncio
import threading
from typing import Set, Optional
import websockets
from rich.console import Console

console = Console()


class GameAudioServer:
    """
    Captures PC system game sound (via PulseAudio / PipeWire monitor)
    and streams raw PCM / audio buffers over WebSocket to the phone.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8901):
        self.host = host
        self.port = port
        self.running = False
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.pipeline = None
        self.sink = None
        self._init_audio_pipeline()

    def _init_audio_pipeline(self):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            Gst.init(None)

            # Record system audio output (monitor of default audio sink)
            pipeline_str = (
                "pulsesrc ! audioconvert ! audioresample ! "
                "audio/x-raw,format=S16LE,rate=44100,channels=2 ! "
                "appsink name=asink emit-signals=True max-buffers=8 drop=True"
            )
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.sink = self.pipeline.get_by_name("asink")
            self.pipeline.set_state(Gst.State.PLAYING)
            console.print("[AUDIO] Initialized system game audio capture (PulseAudio/PipeWire)")
        except Exception as e:
            console.print(f"[AUDIO] Audio capture unavailable ({e}) - video & gamepad stream active.")
            self.pipeline = None
            self.sink = None

    async def client_handler(self, websocket):
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    async def _capture_and_broadcast_loop(self):
        while self.running:
            if self.clients and self.sink:
                try:
                    import gi
                    gi.require_version("Gst", "1.0")
                    from gi.repository import Gst
                    sample = self.sink.emit("pull-sample")
                    if sample:
                        buf = sample.get_buffer()
                        success, map_info = buf.map(Gst.MapFlags.READ)
                        if success:
                            audio_bytes = bytes(map_info.data)
                            buf.unmap(map_info)
                            if audio_bytes:
                                websockets.broadcast(self.clients, audio_bytes)
                except Exception:
                    pass
            await asyncio.sleep(0.01)

    async def start(self):
        self.running = True
        console.print(f"[AUDIO] GameGhost Audio listening on ws://{self.host}:{self.port}")
        server = await websockets.serve(
            self.client_handler,
            self.host,
            self.port,
            max_size=1024 * 1024,
            ping_interval=20,
            ping_timeout=20
        )
        await asyncio.gather(server.wait_closed(), self._capture_and_broadcast_loop())

    def stop(self):
        self.running = False
        if self.pipeline:
            try:
                import gi
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst
                self.pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self.pipeline = None
