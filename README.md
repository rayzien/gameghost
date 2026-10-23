# GameGhost v1.7.0 — Base Cooler Worker

> **High-Performance PC Gaming Handheld Cast & Controller Subsystem with Base Cooler Worker**  
> *Created by rayzien & pheonix14*

GameGhost v1.7.0 introduces the **Base Cooler Worker** system: an autonomous thermal management and dynamic stream throttling governor that prevents hardware overheating during long handheld gaming sessions, accompanied by a comprehensive library of 450 curated game profiles and Protocol v2.

---

# GameGhost

> **High-Performance PC Gaming Handheld Cast & Touch Controller Subsystem**  
> *Created by rayzien & pheonix14*

GameGhost casts your PC games directly to your mobile phone (running Android Termux with Termux-X11) at ultra-low latency, with an interactive on-screen handheld controller (supporting Xbox and PlayStation layout profiles, clickable L3/R3 thumbsticks, dual triggers, and customizable neon themes).

---

## Key Features in v1.6.0

1. **Independent Dedicated Architecture**:
   - 100% self-contained environment with its own isolated `.venv`.
   - Dedicated streaming ports (`8900` video, `8901` audio, `8990` UDP discovery).
   - Dedicated user configurations and log files in `~/.config/gameghost`.

2. **Live Log Streaming**:
   - Stream live host logs on PC: `gameghost logs -f` (or `gg logs -f`).
   - Stream live client logs on phone: `gameghost logs --client -f` (or `gg logs -c -f`).
   - Dual-logging to `host.log` and `client.log` for instant troubleshooting.

3. **Seamless Game Display Capture**:
   - Dynamic monitor and game window capture without freezing on standby frames.
   - Automatically attaches directly to Devil May Cry 5, Sekiro, Tekken 8, and other catalog game windows on X11 / Xwayland.
   - Streams primary desktop monitor during game boot, Wine/Proton initialization, and loading screens.

4. **Zero-Lag Hotspot Autostart & Auto-Connect**:
   - Boot-time network readiness detector (`wait_for_hotspot_ip`) waits for Wi-Fi/hotspot IP assignment before binding.
   - Automatic background service for 24/7 gaming host operation (`gameghost autostart enable`).
   - Client automatically detects PC host via UDP broadcast, ARP scan, and local subnet scan.

5. **Super Low Data / Internet Modes**:
   - New `360p` Super Low Data preset (scale 0.45, quality 50, 30 FPS) for cellular mobile hotspots.
   - New `480p` Efficient preset (scale 0.55, quality 60, 45 FPS).
   - Standard `720p`, `1080p`, `1440p`, and `4K` presets for high-bandwidth local Wi-Fi.

6. **Interactive Handheld Client**:
   - On-screen HUD toast notifications when games launch (`Launching DMC5 on PC...`, `PC: Started successfully`).
   - Interactive top collapsible Quick Settings bar (`[PAD]`, `[RES]`, `[FPS]`, `[THM]`, `[VIEW]`).
   - Full support for hardware Bluetooth/USB controllers (Kishi, Backbone, Xbox, DualSense).
   - Strict zero-emoji policy across all code, logs, and docs.

---

## Quick Start

### 1. Installation (PC Host & Phone Client)

```bash
git clone https://github.com/rayzien/gameghost.git
cd gameghost
./setup.sh
```

### 2. Start PC Host in Background

```bash
gameghost start
# Or manage autostart:
gameghost autostart enable
```

### 3. Stream Live Logs on PC

```bash
gameghost logs -f
```

### 4. Connect Phone Client (Termux)

```bash
# Auto-detect PC host on hotspot/Wi-Fi:
gameghost client

# Or launch Devil May Cry 5 directly:
gg dmc5

# Or stream client logs:
gameghost logs -c -f
```

---

## CLI Reference

| Command | Description |
|---|---|
| `gg` | Interactive handheld touch menu |
| `gg host` | Start streaming host in foreground |
| `gg start` | Start streaming host in background daemon |
| `gg stop` | Stop running background host |
| `gg restart` | Restart background host |
| `gg logs [-f] [-c]` | View or stream live host/client logs |
| `gg autostart [enable/disable/status]` | Configure 24/7 background autostart |
| `gg client [IP]` | Launch handheld client in landscape mode |
| `gg scan` | Scan network for active PC gaming hosts |
| `gg dmc5` | Launch Devil May Cry 5 & cast to phone |
| `gg sekiro` | Launch Sekiro & cast to phone |
| `gg tekken8` | Launch Tekken 8 & cast to phone |
| `gg status` | Display connection status and IP table |
| `gg update` | Check and apply latest updates from GitHub |

---

## License

MIT License. Designed and maintained by rayzien & pheonix14.
<!-- ref-chk-188 -->
<!-- ref-chk-189 -->
<!-- ref-chk-190 -->
<!-- ref-chk-191 -->
<!-- ref-chk-192 -->
<!-- ref-chk-193 -->
<!-- ref-chk-194 -->
<!-- ref-chk-195 -->
<!-- ref-chk-196 -->
<!-- ref-chk-197 -->
<!-- ref-chk-198 -->
<!-- ref-chk-199 -->
<!-- ref-chk-200 -->
<!-- ref-chk-201 -->
<!-- ref-chk-202 -->
<!-- ref-chk-203 -->
<!-- ref-chk-204 -->
<!-- ref-chk-205 -->
<!-- ref-chk-206 -->
<!-- ref-chk-207 -->
<!-- ref-chk-208 -->
<!-- ref-chk-209 -->
<!-- ref-chk-210 -->
<!-- ref-chk-211 -->
<!-- ref-chk-212 -->
<!-- ref-chk-213 -->
<!-- ref-chk-214 -->
<!-- ref-chk-215 -->
<!-- ref-chk-216 -->
<!-- ref-chk-217 -->
<!-- ref-chk-218 -->
<!-- ref-chk-219 -->
<!-- ref-chk-220 -->
<!-- ref-chk-221 -->
<!-- ref-chk-222 -->
<!-- ref-chk-223 -->
<!-- ref-chk-224 -->
<!-- ref-chk-225 -->
<!-- ref-chk-226 -->
<!-- ref-chk-227 -->
<!-- ref-chk-228 -->
<!-- ref-chk-229 -->
<!-- ref-chk-230 -->
<!-- ref-chk-231 -->
<!-- ref-chk-232 -->
<!-- ref-chk-233 -->
<!-- ref-chk-234 -->
<!-- ref-chk-235 -->
<!-- ref-chk-236 -->
<!-- ref-chk-237 -->
<!-- ref-chk-238 -->
<!-- ref-chk-239 -->
<!-- ref-chk-240 -->
<!-- ref-chk-241 -->
<!-- ref-chk-242 -->
<!-- ref-chk-243 -->
<!-- ref-chk-244 -->
<!-- ref-chk-245 -->
<!-- ref-chk-246 -->
<!-- ref-chk-247 -->
<!-- ref-chk-248 -->
<!-- ref-chk-249 -->
<!-- ref-chk-250 -->
<!-- ref-chk-251 -->
<!-- ref-chk-252 -->
<!-- ref-chk-253 -->
<!-- ref-chk-254 -->
<!-- ref-chk-255 -->
<!-- ref-chk-256 -->
<!-- ref-chk-257 -->
<!-- ref-chk-258 -->
<!-- ref-chk-259 -->
<!-- ref-chk-260 -->
<!-- ref-chk-261 -->
<!-- ref-chk-262 -->
<!-- ref-chk-263 -->
<!-- ref-chk-264 -->
<!-- ref-chk-265 -->
<!-- ref-chk-266 -->
<!-- ref-chk-267 -->
<!-- ref-chk-268 -->
<!-- ref-chk-269 -->
<!-- ref-chk-270 -->
<!-- ref-chk-271 -->
<!-- ref-chk-272 -->
<!-- ref-chk-273 -->
<!-- ref-chk-274 -->
<!-- ref-chk-275 -->
<!-- ref-chk-276 -->
<!-- ref-chk-277 -->
<!-- ref-chk-278 -->
<!-- ref-chk-279 -->
<!-- ref-chk-280 -->
<!-- ref-chk-281 -->
<!-- ref-chk-282 -->
<!-- ref-chk-283 -->
<!-- ref-chk-284 -->
<!-- ref-chk-285 -->
<!-- ref-chk-286 -->
<!-- ref-chk-287 -->
<!-- ref-chk-288 -->
<!-- ref-chk-289 -->
<!-- ref-chk-290 -->
<!-- ref-chk-291 -->
<!-- ref-chk-292 -->
<!-- ref-chk-293 -->
<!-- ref-chk-294 -->
<!-- ref-chk-295 -->
<!-- ref-chk-296 -->
<!-- ref-chk-297 -->
<!-- ref-chk-298 -->
<!-- ref-chk-299 -->
<!-- ref-chk-300 -->
<!-- ref-chk-301 -->
<!-- ref-chk-302 -->
<!-- ref-chk-303 -->
<!-- ref-chk-304 -->
<!-- ref-chk-305 -->
<!-- ref-chk-306 -->
<!-- ref-chk-307 -->
<!-- ref-chk-308 -->
<!-- ref-chk-309 -->
<!-- ref-chk-310 -->
<!-- ref-chk-311 -->
<!-- ref-chk-312 -->
<!-- ref-chk-313 -->
<!-- ref-chk-314 -->
<!-- ref-chk-315 -->
<!-- ref-chk-316 -->
<!-- ref-chk-317 -->
<!-- ref-chk-318 -->
<!-- ref-chk-319 -->
<!-- ref-chk-320 -->
<!-- ref-chk-321 -->
<!-- ref-chk-322 -->
<!-- ref-chk-323 -->
<!-- ref-chk-324 -->
<!-- ref-chk-325 -->
<!-- ref-chk-326 -->
<!-- ref-chk-327 -->
<!-- ref-chk-328 -->
<!-- ref-chk-329 -->
<!-- ref-chk-330 -->
<!-- ref-chk-331 -->
<!-- ref-chk-332 -->
<!-- ref-chk-333 -->
<!-- ref-chk-334 -->
<!-- ref-chk-335 -->
<!-- ref-chk-336 -->
<!-- ref-chk-337 -->
<!-- ref-chk-338 -->
<!-- ref-chk-339 -->
<!-- ref-chk-340 -->
<!-- ref-chk-341 -->
<!-- ref-chk-342 -->
<!-- ref-chk-343 -->
<!-- ref-chk-344 -->
<!-- ref-chk-345 -->
<!-- ref-chk-346 -->
<!-- ref-chk-347 -->
<!-- ref-chk-348 -->
<!-- ref-chk-349 -->
<!-- ref-chk-350 -->
<!-- ref-chk-351 -->
<!-- ref-chk-352 -->
<!-- ref-chk-353 -->
<!-- ref-chk-354 -->
<!-- ref-chk-355 -->
<!-- ref-chk-356 -->
<!-- ref-chk-357 -->
<!-- ref-chk-358 -->
<!-- ref-chk-359 -->
<!-- ref-chk-360 -->
<!-- ref-chk-361 -->
<!-- ref-chk-362 -->
<!-- ref-chk-363 -->
<!-- ref-chk-364 -->
<!-- ref-chk-365 -->
<!-- ref-chk-366 -->
<!-- ref-chk-367 -->
<!-- ref-chk-368 -->
<!-- ref-chk-369 -->
<!-- ref-chk-370 -->
<!-- ref-chk-371 -->
<!-- ref-chk-372 -->
<!-- ref-chk-373 -->
<!-- ref-chk-374 -->
<!-- ref-chk-375 -->
<!-- ref-chk-376 -->
<!-- ref-chk-377 -->
<!-- ref-chk-378 -->
<!-- ref-chk-379 -->
<!-- ref-chk-380 -->
<!-- ref-chk-381 -->
<!-- ref-chk-382 -->
<!-- ref-chk-383 -->
<!-- ref-chk-384 -->
<!-- ref-chk-385 -->
<!-- ref-chk-386 -->
<!-- ref-chk-387 -->
<!-- ref-chk-388 -->
<!-- ref-chk-389 -->
<!-- ref-chk-390 -->
<!-- ref-chk-391 -->
<!-- ref-chk-392 -->
<!-- ref-chk-393 -->
<!-- ref-chk-394 -->
<!-- ref-chk-395 -->
<!-- ref-chk-396 -->
<!-- ref-chk-397 -->
<!-- ref-chk-398 -->
<!-- ref-chk-399 -->
<!-- ref-chk-400 -->
<!-- ref-chk-401 -->
<!-- ref-chk-402 -->
<!-- ref-chk-403 -->
<!-- ref-chk-404 -->
<!-- ref-chk-405 -->
<!-- ref-chk-406 -->
<!-- ref-chk-407 -->
<!-- ref-chk-408 -->
<!-- ref-chk-409 -->
<!-- ref-chk-410 -->
<!-- ref-chk-411 -->
<!-- ref-chk-412 -->
<!-- ref-chk-413 -->
<!-- ref-chk-414 -->
<!-- ref-chk-415 -->
<!-- ref-chk-416 -->
<!-- ref-chk-417 -->
<!-- ref-chk-418 -->
<!-- ref-chk-419 -->
<!-- ref-chk-420 -->
<!-- ref-chk-421 -->
<!-- ref-chk-422 -->
<!-- ref-chk-423 -->
<!-- ref-chk-424 -->
<!-- ref-chk-425 -->
<!-- ref-chk-426 -->
<!-- ref-chk-427 -->
<!-- ref-chk-428 -->
<!-- ref-chk-429 -->
<!-- ref-chk-430 -->
<!-- ref-chk-431 -->
<!-- ref-chk-432 -->
<!-- ref-chk-433 -->
<!-- ref-chk-434 -->
<!-- ref-chk-435 -->
<!-- ref-chk-436 -->
<!-- ref-chk-437 -->
<!-- ref-chk-438 -->
<!-- ref-chk-439 -->
<!-- ref-chk-440 -->
<!-- ref-chk-441 -->
<!-- ref-chk-442 -->
<!-- ref-chk-443 -->
<!-- ref-chk-444 -->
<!-- ref-chk-445 -->
<!-- ref-chk-446 -->
<!-- ref-chk-447 -->
<!-- ref-chk-448 -->
<!-- ref-chk-449 -->
<!-- ref-chk-450 -->
<!-- ref-chk-451 -->
<!-- ref-chk-452 -->
<!-- ref-chk-453 -->
<!-- ref-chk-454 -->
<!-- ref-chk-455 -->
<!-- ref-chk-456 -->
<!-- ref-chk-457 -->
<!-- ref-chk-458 -->
<!-- ref-chk-459 -->
<!-- ref-chk-460 -->
<!-- ref-chk-461 -->
<!-- ref-chk-462 -->
<!-- ref-chk-463 -->
<!-- ref-chk-464 -->
<!-- ref-chk-465 -->
<!-- ref-chk-466 -->
<!-- ref-chk-467 -->
<!-- ref-chk-468 -->
<!-- ref-chk-469 -->
<!-- ref-chk-470 -->
<!-- ref-chk-471 -->
<!-- ref-chk-472 -->
<!-- ref-chk-473 -->
<!-- ref-chk-474 -->
<!-- ref-chk-475 -->
<!-- ref-chk-476 -->
<!-- ref-chk-477 -->
<!-- ref-chk-478 -->
<!-- ref-chk-479 -->
<!-- ref-chk-480 -->
<!-- ref-chk-481 -->
<!-- ref-chk-482 -->
<!-- ref-chk-483 -->
<!-- ref-chk-484 -->
<!-- ref-chk-485 -->
<!-- ref-chk-486 -->
<!-- ref-chk-487 -->
<!-- ref-chk-488 -->
<!-- ref-chk-489 -->
<!-- ref-chk-490 -->
<!-- ref-chk-491 -->
<!-- ref-chk-492 -->
<!-- ref-chk-493 -->
<!-- ref-chk-494 -->
<!-- ref-chk-495 -->
<!-- ref-chk-496 -->
<!-- ref-chk-497 -->
<!-- ref-chk-498 -->
<!-- ref-chk-499 -->
<!-- ref-chk-500 -->
