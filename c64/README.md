# Simple-Train C64 throttle

A throttle for the **Commodore 64 Ultimate** (it also suits the Ultimate 64 and the 1541
Ultimate-II+). It drives trains and switches points through Simple-Train on the PC, over the
network, in the same way that Engine Driver does on a phone.

## Setting up

1. **On the PC:** in Simple-Train, connect to the NCE as usual. Then, on the **Throttles** tab,
   tick **Let phones drive**. The line next to the tick shows the PC's address.
2. **On the C64 Ultimate:** in the Ultimate menu, go to **C64 and Cartridge Settings → Command
   Interface** and choose **Enabled**. The network must be set up too. If the weather program works,
   it already is.
3. Run `simple-train-c64.prg`, for example from a USB stick in the Ultimate's file browser.
4. Type the PC's address (it suggests 192.168.1.201) and press RETURN.

## Using it

- **Choose a loco:** use up and down (the cursor keys or the joystick), then RETURN or fire. Or
  press **A** to type an address.
- **Drive:**
  - Speed: the joystick in port 2 up and down, the cursor keys up and down, or **+** and **-** to
    change it by ten.
  - Direction: the joystick left and right, or the cursor keys left and right.
  - Stop: **fire** or **SPACE**. Emergency stop: **RUN/STOP** or **E**.
  - Functions: keys **0–9** work F0–F9, and the **F1 F3 F5** keys work F10–F12. The screen shows the
    function names from the roster.
  - Other screens: **L** for the loco list, **P** for points, **Q** to disconnect.
- **Points:** choose a point and press RETURN (or fire) to switch it, and **←** to go back.

Changes made elsewhere, in the app or on a phone, show up on the C64 straight away. The C64 sends
a heartbeat, so if it's switched off or loses the network, Simple-Train stops its loco.

## Building

You need cc65 (`sudo apt install cc65`):

```bash
make -C c64                            # simple-train-c64.prg
make -C c64 SERVER_IP=192.168.1.50     # suggest a different PC address
make -C c64 test                       # the protocol tests, run on the PC
```

`src/uci.c` is a small driver for the Ultimate Command Interface. It was written from the official
register description, not taken from another library. `src/wt.c` is the WiThrottle side, and
`src/main.c` holds the screens.
