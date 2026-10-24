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


def _find_speaker_monitor() -> str:
    """Find the exact PipeWire speaker sink or monitor target."""
    return "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink"


def _link_game_audio_source():
    """
    Ensure pw-record is linked exclusively to the running game's audio output,
    or the Speaker monitor sink, and never the microphone.
    """
    try:
        # Find all game output ports (Wine, Polaris, Tekken, DMC5, etc.)
        res_out = subprocess.run(["pw-link", "-o"], capture_output=True, text=True, timeout=1.0)
        game_fl = None
        game_fr = None
        for line in res_out.stdout.splitlines():
            line = line.strip()
            l_lower = line.lower()
            if any(k in l_lower for k in ("wine", "polaris", "tekken", "devil", "sekiro", "mk11", "mgr", "rottr")):
                if "fl" in l_lower or "left" in l_lower or "playback_fl" in l_lower or "output_fl" in l_lower or "output_1" in l_lower:
                    game_fl = line
                elif "fr" in l_lower or "right" in l_lower or "playback_fr" in l_lower or "output_fr" in l_lower or "output_2" in l_lower:
                    game_fr = line

        # Fallback to speaker monitor
        if not game_fl or not game_fr:
            game_fl = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink:monitor_FL"
            game_fr = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink:monitor_FR"

        # Disconnect all microphone links to pw-record
        res_links = subprocess.run(["pw-link", "-l"], capture_output=True, text=True, timeout=1.0)
        for line in res_links.stdout.splitlines():
            line_str = line.strip()
            if "mic" in line_str.lower() and "pw-record" in line_str:
                parts = line_str.split()
                if len(parts) >= 3 and parts[1] == "|->":
                    subprocess.run(["pw-link", "-d", parts[0], parts[2]], capture_output=True, timeout=0.5)

        # Link target ports to pw-record
        if game_fl:
            subprocess.run(["pw-link", game_fl, "pw-record:input_FL"], capture_output=True, timeout=0.5)
        if game_fr:
            subprocess.run(["pw-link", game_fr, "pw-record:input_FR"], capture_output=True, timeout=0.5)
    except Exception:
        pass


def _get_capture_command() -> Optional[list]:
    """Find the best available low-latency system audio capture tool."""
    if shutil.which("pw-record"):
        return ["pw-record", "--format", "s16", "--rate", "44100", "--channels", "2", "-"]
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
                time.sleep(0.3)
                _link_game_audio_source()

                loop_count = 0
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

                    loop_count += 1
                    if loop_count % 50 == 0:
                        _link_game_audio_source()
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
        last_audio_telemetry = time.time()
        chunks_broadcasted = 0
        while self.running:
            if self.clients:
                self._last_client_time = time.time()
                try:
                    # Drain queue and broadcast newest available chunks
                    while not self.audio_queue.empty():
                        chunk = self.audio_queue.get_nowait()
                        if chunk and self.clients:
                            websockets.broadcast(self.clients, chunk)
                            chunks_broadcasted += 1
                except Exception:
                    pass

                now = time.time()
                if now - last_audio_telemetry >= 4.0:
                    last_audio_telemetry = now
                    console.print(f"[bold magenta][AUDIO TELEMETRY][/bold magenta] Source: Isolated Game / Speaker Monitor | Rate: 44.1kHz Stereo PCM | Clients: {len(self.clients)} | Packets: {chunks_broadcasted}")
                    log_host(f"[AUDIO TELEMETRY] Source=GameAudio/Speaker Rate=44.1kHz Stereo Clients={len(self.clients)} Packets={chunks_broadcasted}")
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
