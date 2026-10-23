import os
import sys
import time
import queue
import shutil
import asyncio
import threading
import subprocess
from typing import Set, Optional
import websockets
from rich.console import Console

from .config import log_host

console = Console()


def _get_capture_command() -> Optional[list]:
    """Find the best available low-latency system audio capture tool."""
    if shutil.which("pw-record"):
        return ["pw-record", "--target", "@DEFAULT_AUDIO_SINK@", "--format", "s16", "--rate", "44100", "--channels", "2", "-"]
    if shutil.which("parec"):
        return ["parec", "--format=s16le", "--rate=44100", "--channels=2"]
    if shutil.which("ffmpeg"):
        return ["ffmpeg", "-nostdin", "-loglevel", "quiet", "-f", "pulse", "-i", "default", "-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    return None


class GameAudioServer:
    """
    Captures PC system game sound (via PipeWire / PulseAudio monitor)
    and streams raw PCM audio buffers over WebSocket to the phone.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8901):
        self.host = host
        self.port = port
        self.running = False
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.audio_queue = queue.Queue(maxsize=16)
        self.capture_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None
        self._last_client_time = time.time()

    def _start_capture(self):
        """Start background capture worker if not already running."""
        if self.capture_thread and self.capture_thread.is_alive():
            return

        cmd = _get_capture_command()
        if not cmd:
            console.print("[bold yellow][AUDIO][/bold yellow] No PipeWire / PulseAudio recording tool found.")
            log_host("Audio capture disabled: no suitable tool (pw-record, parec, ffmpeg) found")
            return

        self.stop_event.clear()

        def _worker():
            try:
                console.print(f"[bold green][AUDIO][/bold green] Starting system audio capture via {cmd[0]}...")
                log_host(f"Audio capture started using {cmd[0]}")
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=4096
                )
                while not self.stop_event.is_set() and self.proc and self.proc.poll() is None:
                    data = self.proc.stdout.read(4096)
                    if not data:
                        break
                    # Drop oldest if queue is full to avoid latency drift
                    if self.audio_queue.full():
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.audio_queue.put_nowait(data)
            except Exception as ex:
                log_host(f"Audio capture worker exception: {ex}")
            finally:
                if self.proc:
                    try:
                        self.proc.terminate()
                        self.proc.wait(timeout=0.5)
                    except Exception:
                        try:
                            self.proc.kill()
                        except Exception:
                            pass
                    self.proc = None
                log_host("Audio capture worker stopped")

        self.capture_thread = threading.Thread(target=_worker, daemon=True)
        self.capture_thread.start()

    def _stop_capture(self):
        """Stop background capture worker to save host resources."""
        self.stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.capture_thread = None

    async def client_handler(self, websocket):
        self.clients.add(websocket)
        self._last_client_time = time.time()
        console.print(f"[bold green][AUDIO][/bold green] Phone client connected for audio stream ({len(self.clients)} active)")
        log_host(f"Audio client connected (active: {len(self.clients)})")
        self._start_capture()
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)
            console.print(f"[bold yellow][AUDIO][/bold yellow] Audio client disconnected ({len(self.clients)} active)")
            log_host(f"Audio client disconnected (active: {len(self.clients)})")

    async def _capture_and_broadcast_loop(self):
        while self.running:
            if self.clients:
                self._last_client_time = time.time()
                try:
                    # Drain queue and broadcast newest available chunks
                    while not self.audio_queue.empty():
                        chunk = self.audio_queue.get_nowait()
                        if chunk and self.clients:
                            websockets.broadcast(self.clients, chunk)
                except Exception:
                    pass
            else:
                # If idle for more than 5 seconds without clients, stop capture
                if time.time() - self._last_client_time > 5.0 and self.capture_thread:
                    self._stop_capture()

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
        self._stop_capture()
