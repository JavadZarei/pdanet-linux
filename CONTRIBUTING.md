# Contributing

```bash
python3 -m unittest discover -s tests/unit          # no hardware needed
xvfb-run -a python3 tests/ui_smoke.py               # needs python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
MAINTAINER="Your Name <you@example.com>" ./build-deb.sh
```

Ground rules

* The USB protocol, TUN, routing and DNS logic live in `bin/pdanet` and `libexec/pdanet-usb-helper`.
  Please open an issue before changing them; the GUI is designed to drive them unchanged.
* No shell strings: run commands as argument lists with timeouts (`gui/pdanet_gui/core/runner.py`).
* `libexec/pdanet-gui-helper` runs as root. Any change to it needs tests in `tests/unit/test_helper_and_i18n.py`.
* Every user-visible string goes into both `EN` and `FA` in `gui/pdanet_gui/i18n.py` (a test enforces this).
