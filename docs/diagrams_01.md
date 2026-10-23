# GameGhost Architecture & Sequence Flow Diagram 01

```
Phone (Termux-X11) <====[ WebSocket 8900 ]====> Host Server (MSS / Xwayland)
       |                                                 |
  Touch Inputs                                    Base Cooler Worker
       |                                                 |
       v                                                 v
Hardware uinput Pad <=========================== Dynamic Thermal Governor
```
