// GameGhost Handheld Client
// Ultra-low latency video rendering & multi-touch virtual gamepad

(function() {
    const host = window.location.hostname || "127.0.0.1";
    const streamWsUrl = `ws://${host}:8900`;
    const audioWsUrl = `ws://${host}:8901`;

    let streamWs = null;
    let audioWs = null;
    let audioCtx = null;
    let wakeLock = null;
    let vibrationEnabled = true;

    // Elements
    const canvas = document.getElementById("game-canvas");
    const ctx = canvas.getContext("2d", { alpha: false });
    const loadingOverlay = document.getElementById("loading-overlay");
    const connStatus = document.getElementById("conn-status");
    const fpsTag = document.getElementById("fps-tag");
    const latencyTag = document.getElementById("latency-tag");
    const btnFullscreen = document.getElementById("btn-fullscreen");
    const btnFullscreenPrompt = document.getElementById("btn-fullscreen-prompt");
    const btnAudio = document.getElementById("btn-audio");
    const btnSettings = document.getElementById("btn-settings");
    const settingsModal = document.getElementById("settings-modal");
    const btnCloseSettings = document.getElementById("btn-close-settings");

    // Performance Stats
    let framesDrawn = 0;
    let lastFpsUpdate = performance.now();
    let currentFps = 0;
    let lastPingSend = 0;

    // -------------------------------------------------------------------------
    // 1. Wake Lock & Fullscreen
    // -------------------------------------------------------------------------
    async function requestWakeLock() {
        try {
            if ("wakeLock" in navigator) {
                wakeLock = await navigator.wakeLock.request("screen");
                console.log("[WAKELOCK] Active - display will not sleep while playing.");
            }
        } catch (e) {
            console.log("[WAKELOCK] Not supported or failed:", e);
        }
    }

    function toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(() => {});
            if (screen.orientation && screen.orientation.lock) {
                screen.orientation.lock("landscape").catch(() => {});
            }
            requestWakeLock();
        } else {
            document.exitFullscreen().catch(() => {});
        }
    }

    btnFullscreen.addEventListener("click", toggleFullscreen);
    btnFullscreenPrompt.addEventListener("click", () => {
        toggleFullscreen();
        initAudio();
    });

    // -------------------------------------------------------------------------
    // 2. Video Stream WebSocket
    // -------------------------------------------------------------------------
    function connectStream() {
        connStatus.innerText = "Connecting to Game Stream...";
        streamWs = new WebSocket(streamWsUrl);
        streamWs.binaryType = "blob";

        streamWs.onopen = () => {
            console.log("[STREAM] Connected to PC GameGhost Server");
            connStatus.innerText = "Connected! Waiting for frames...";
            loadingOverlay.style.display = "none";
            requestWakeLock();
            startPingLoop();
        };

        streamWs.onmessage = (event) => {
            if (event.data instanceof Blob) {
                // Video frame received
                createImageBitmap(event.data).then((bmp) => {
                    if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
                        canvas.width = bmp.width;
                        canvas.height = bmp.height;
                    }
                    ctx.drawImage(bmp, 0, 0);
                    bmp.close();

                    framesDrawn++;
                    const now = performance.now();
                    if (now - lastFpsUpdate >= 1000) {
                        currentFps = framesDrawn;
                        framesDrawn = 0;
                        lastFpsUpdate = now;
                        fpsTag.innerText = `${currentFps} FPS`;
                    }
                }).catch(() => {});
            } else if (typeof event.data === "string") {
                try {
                    const data = jsonParse(event.data);
                    if (data && data.type === "pong") {
                        const rtt = Math.round(performance.now() - lastPingSend);
                        latencyTag.innerText = `${rtt} ms`;
                    }
                } catch (e) {}
            }
        };

        streamWs.onclose = () => {
            console.log("[STREAM] Closed. Reconnecting in 2s...");
            loadingOverlay.style.display = "flex";
            connStatus.innerText = "Connection lost. Reconnecting...";
            setTimeout(connectStream, 2000);
        };

        streamWs.onerror = () => {
            streamWs.close();
        };
    }

    function startPingLoop() {
        setInterval(() => {
            if (streamWs && streamWs.readyState === WebSocket.OPEN) {
                lastPingSend = performance.now();
                streamWs.send(JSON.stringify({ type: "ping", time: lastPingSend }));
            }
        }, 2000);
    }

    function sendInput(packet) {
        if (streamWs && streamWs.readyState === WebSocket.OPEN) {
            streamWs.send(JSON.stringify(packet));
        }
    }

    function vibrate(ms = 15) {
        if (vibrationEnabled && navigator.vibrate) {
            try { navigator.vibrate(ms); } catch (e) {}
        }
    }

    function jsonParse(str) {
        try { return JSON.parse(str); } catch (e) { return null; }
    }

    // -------------------------------------------------------------------------
    // 3. Audio Streaming (WebAudio)
    // -------------------------------------------------------------------------
    function initAudio() {
        if (audioCtx) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 44100 });
            audioWs = new WebSocket(audioWsUrl);
            audioWs.binaryType = "arraybuffer";

            audioWs.onmessage = (event) => {
                if (audioCtx && audioCtx.state === "suspended") {
                    audioCtx.resume();
                }
                const pcm16 = new Int16Array(event.data);
                if (pcm16.length === 0) return;

                const channels = 2;
                const frameCount = pcm16.length / channels;
                const audioBuffer = audioCtx.createBuffer(channels, frameCount, 44100);

                const left = audioBuffer.getChannelData(0);
                const right = audioBuffer.getChannelData(1);

                for (let i = 0; i < frameCount; i++) {
                    left[i] = pcm16[i * 2] / 32768.0;
                    right[i] = pcm16[i * 2 + 1] / 32768.0;
                }

                const source = audioCtx.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioCtx.destination);
                source.start();
            };
            btnAudio.innerText = "🔊";
        } catch (e) {
            console.log("[AUDIO] Audio initialization error:", e);
        }
    }

    btnAudio.addEventListener("click", () => {
        if (!audioCtx) {
            initAudio();
        } else if (audioCtx.state === "running") {
            audioCtx.suspend();
            btnAudio.innerText = "🔇";
        } else {
            audioCtx.resume();
            btnAudio.innerText = "🔊";
        }
    });

    // -------------------------------------------------------------------------
    // 4. On-Screen Buttons (D-Pad, Triggers, Actions, HUD Buttons)
    // -------------------------------------------------------------------------
    const activeButtons = new Set();

    function setupButton(el, getPacket) {
        if (!el) return;

        const press = (e) => {
            e.preventDefault();
            e.stopPropagation();
            el.classList.add("active");
            vibrate(18);
            sendInput(getPacket(1));
        };

        const release = (e) => {
            e.preventDefault();
            e.stopPropagation();
            el.classList.remove("active");
            sendInput(getPacket(0));
        };

        el.addEventListener("touchstart", press, { passive: false });
        el.addEventListener("touchend", release, { passive: false });
        el.addEventListener("touchcancel", release, { passive: false });
        el.addEventListener("mousedown", press);
        el.addEventListener("mouseup", release);
        el.addEventListener("mouseleave", release);
    }

    // Standard Gamepad Buttons (A, B, X, Y, L1, R1, L2, R2, SELECT, START, HOME)
    document.querySelectorAll("[data-btn]").forEach(btn => {
        const btnName = btn.getAttribute("data-btn");
        if (btnName === "L2" || btnName === "R2") {
            setupButton(btn, (val) => ({ type: "trigger", name: btnName, val: val }));
        } else {
            setupButton(btn, (val) => ({ type: "btn", name: btnName, val: val }));
        }
    });

    // D-Pad Buttons
    const dpadState = { up: 0, down: 0, left: 0, right: 0 };
    function sendDpad() {
        const dx = dpadState.right - dpadState.left;
        const dy = dpadState.down - dpadState.up;
        sendInput({ type: "dpad", x: dx, y: dy });
    }

    document.querySelectorAll("[data-dpad]").forEach(btn => {
        const dir = btn.getAttribute("data-dpad");
        setupButton(btn, (val) => {
            dpadState[dir] = val;
            sendDpad();
            return { type: "noop" };
        });
    });

    // -------------------------------------------------------------------------
    // 5. Multi-Touch Analog Thumbsticks (Left: Movement, Right: Camera)
    // -------------------------------------------------------------------------
    class TouchStick {
        constructor(zoneId, baseId, knobId, which) {
            this.zone = document.getElementById(zoneId);
            this.base = document.getElementById(baseId);
            this.knob = document.getElementById(knobId);
            this.which = which; // "left" or "right"
            this.activeTouchId = null;
            this.radius = 50; // max distance from center
            this.centerX = 0;
            this.centerY = 0;
            this.initListeners();
        }

        initListeners() {
            if (!this.zone) return;

            this.zone.addEventListener("touchstart", (e) => this.onTouchStart(e), { passive: false });
            window.addEventListener("touchmove", (e) => this.onTouchMove(e), { passive: false });
            window.addEventListener("touchend", (e) => this.onTouchEnd(e), { passive: false });
            window.addEventListener("touchcancel", (e) => this.onTouchEnd(e), { passive: false });

            // Mouse fallback for testing on PC
            let mouseActive = false;
            this.zone.addEventListener("mousedown", (e) => {
                mouseActive = true;
                const rect = this.base.getBoundingClientRect();
                this.centerX = rect.left + rect.width / 2;
                this.centerY = rect.top + rect.height / 2;
                this.updatePosition(e.clientX, e.clientY);
            });
            window.addEventListener("mousemove", (e) => {
                if (mouseActive) this.updatePosition(e.clientX, e.clientY);
            });
            window.addEventListener("mouseup", () => {
                if (mouseActive) {
                    mouseActive = false;
                    this.reset();
                }
            });
        }

        onTouchStart(e) {
            if (this.activeTouchId !== null) return;
            const touch = e.changedTouches[0];
            this.activeTouchId = touch.identifier;

            const rect = this.base.getBoundingClientRect();
            this.centerX = rect.left + rect.width / 2;
            this.centerY = rect.top + rect.height / 2;

            this.updatePosition(touch.clientX, touch.clientY);
            vibrate(10);
            e.preventDefault();
        }

        onTouchMove(e) {
            if (this.activeTouchId === null) return;
            for (let i = 0; i < e.changedTouches.length; i++) {
                const touch = e.changedTouches[i];
                if (touch.identifier === this.activeTouchId) {
                    this.updatePosition(touch.clientX, touch.clientY);
                    e.preventDefault();
                    break;
                }
            }
        }

        onTouchEnd(e) {
            if (this.activeTouchId === null) return;
            for (let i = 0; i < e.changedTouches.length; i++) {
                if (e.changedTouches[i].identifier === this.activeTouchId) {
                    this.activeTouchId = null;
                    this.reset();
                    e.preventDefault();
                    break;
                }
            }
        }

        updatePosition(touchX, touchY) {
            const dx = touchX - this.centerX;
            const dy = touchY - this.centerY;
            const dist = Math.hypot(dx, dy);

            let clampedX = dx;
            let clampedY = dy;
            if (dist > this.radius) {
                clampedX = (dx / dist) * this.radius;
                clampedY = (dy / dist) * this.radius;
            }

            this.knob.style.transform = `translate(${clampedX}px, ${clampedY}px)`;

            // Normalized (-1.0 to 1.0)
            const normX = clampedX / this.radius;
            const normY = clampedY / this.radius;

            // Apply deadzone (5%)
            const finalX = Math.abs(normX) < 0.05 ? 0 : normX;
            const finalY = Math.abs(normY) < 0.05 ? 0 : normY;

            sendInput({
                type: "stick",
                which: this.which,
                x: Number(finalX.toFixed(3)),
                y: Number(finalY.toFixed(3))
            });
        }

        reset() {
            this.knob.style.transform = "translate(0px, 0px)";
            sendInput({
                type: "stick",
                which: this.which,
                x: 0,
                y: 0
            });
        }
    }

    const leftStick = new TouchStick("left-stick-zone", "left-stick-base", "left-stick-knob", "left");
    const rightStick = new TouchStick("right-stick-zone", "right-stick-base", "right-stick-knob", "right");

    // -------------------------------------------------------------------------
    // 6. Settings Modal
    // -------------------------------------------------------------------------
    btnSettings.addEventListener("click", () => {
        settingsModal.classList.remove("hidden");
    });

    btnCloseSettings.addEventListener("click", () => {
        const quality = document.getElementById("setting-quality").value;
        const fps = document.getElementById("setting-fps").value;
        const mode = document.getElementById("setting-mode").value;
        vibrationEnabled = document.getElementById("setting-vibrate").checked;

        sendInput({
            type: "settings",
            quality: parseInt(quality),
            fps: parseInt(fps),
            mode: mode
        });

        settingsModal.classList.add("hidden");
    });

    // Start streaming connection on load
    window.addEventListener("DOMContentLoaded", () => {
        connectStream();
    });
})();
