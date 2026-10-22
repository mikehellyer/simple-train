# Simple-Train

Model railway control for DCC, in the spirit of [iTrain](https://berros.eu/en/itrain/).
The plan is to grow it step by step. The first step is a **decoder programmer for NCE systems**,
working through the **NCE USB interface**.

## What it does so far

- **Connect** to the NCE USB interface: pick its serial port (it's usually `/dev/ttyUSB0` on Linux,
  `COMn` on Windows, or `/dev/cu.SLAB_USBtoUART` on a Mac). You can also pick **Demo (no hardware)**
  to try everything against a pretend command station.
- **Program on the programming track** in direct, paged or register mode, or **on the main (POM)**.
- **Decoder page**: reads who made the decoder (CV8, plus the version in CV7) and which address it
  answers to. You can write a new short or long address there, and CV29 is updated to match while
  keeping its other options. You can also reset the decoder to factory settings (CV8 = 8).
- **Options (CV29)**: swap the direction, choose the speed steps, allow DC running, turn RailCom on,
  use the speed table, and switch between the long and short address.
- **Speed & motor**: start, mid and top voltage, and acceleration and deceleration (CV2–6).
- **All CVs**: read or write any CV from 1 to 1024, read a whole range, and edit values in the
  table before writing them.
- An option to **check each write** by reading it back.
- **Loco roster** (the Locos tab): each loco with its name, running number, DCC address, decoder and
  notes, plus a saved copy of its CVs. **Save to roster** in the programmer stores everything read so
  far. **Read decoder** recognises a roster loco by its address, and the All CVs table then shows the
  saved values beside the decoder's, highlighting any differences. **Write saved CVs to decoder**
  puts a loco's CVs back after a reset or a decoder swap. Locos can be exported to a file and
  imported again.

### NCE notes

- Through the USB interface, only a **Power Cab** or a **Twin** has a programming track. With an
  SB3, SB5 or Power Pro, the USB interface can only program on the main, and the app switches to
  that by itself.
- NCE can't read CVs on the main; there it can only write them.
- On a Power Cab, the one track becomes the programming track while a job runs. The main is
  powered again once the job is done.

## Running from source

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt -e .
venv/bin/simple-train
```

On Linux you need permission to use the serial port. The `.deb` installs a udev rule that gives it to
you. When running from source, add yourself to the `dialout` group once, then log out and back in:

```bash
sudo usermod -aG dialout $USER
```

## Tests

```bash
venv/bin/pytest
```

## Building a .deb locally

```bash
venv/bin/pyinstaller --noconfirm packaging/pyinstaller/simple-train.spec && bash packaging/linux/build-deb.sh
```
