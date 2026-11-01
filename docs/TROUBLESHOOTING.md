# Troubleshooting

Always start with the **Logs** tab → *Run diagnostics* → *Copy logs*.

## "The phone link came up, but the Internet check through it failed"

`pdanet usb on` brings up the tunnel and then checks that DNS works through it. In the logs this looks like:

```
pdanet-usb-helper: connected; forwarding IPv4 packets on pdanet0
ERROR  USB activation failed. Check the phone and run 'pdanet usb test'.
dnscrypt-proxy: Get "https://cloudflare-dns.com/dns-query?...": http: server gave HTTP response to HTTPS client
```

The tunnel to the phone works; the DNS-over-HTTPS server could not be reached *through the phone*. A reply
of plain HTTP to a TLS connection usually means something on the mobile network intercepts that endpoint.
(This is a diagnosis from symptoms, not something this project can verify for you.)

The failed attempt is rolled back automatically: no routes, DNS or interface changes remain.

Things to check:

1. The phone itself has working mobile data (Wi-Fi off, open any website).
2. PdaNet+ shows an active session.
3. Try a different DoH endpoint. The DNS server is set by the `stamp` line in
   `/etc/dnscrypt-proxy-pdanet-usb.toml`. The stamps below embed the server IP, so no name lookup is needed:

| Provider | Stamp |
|---|---|
| Cloudflare 1.1.1.1 (default) | `sdns://AgcAAAAAAAAABzEuMS4xLjEAEmNsb3VkZmxhcmUtZG5zLmNvbQovZG5zLXF1ZXJ5` |
| Cloudflare 1.0.0.1 | `sdns://AgcAAAAAAAAABzEuMC4wLjEAEmNsb3VkZmxhcmUtZG5zLmNvbQovZG5zLXF1ZXJ5` |
| Google 8.8.8.8 | `sdns://AgcAAAAAAAAABzguOC44LjgACmRucy5nb29nbGUKL2Rucy1xdWVyeQ` |
| Quad9 9.9.9.9 | `sdns://AgcAAAAAAAAABzkuOS45LjkADWRucy5xdWFkOS5uZXQKL2Rucy1xdWVyeQ` |

   ```bash
   sudo cp -n /etc/dnscrypt-proxy-pdanet-usb.toml /etc/dnscrypt-proxy-pdanet-usb.toml.orig
   sudo sed -i "s|^stamp = .*|stamp = 'PASTE-STAMP-HERE'|" /etc/dnscrypt-proxy-pdanet-usb.toml
   sudo /usr/bin/pdanet usb
   ```

If every endpoint fails, DNS-over-HTTPS is probably blocked on that network altogether.

## Phone is not detected / "waiting for authorization"

* Enable *USB debugging* in Developer options and accept the "Allow USB debugging?" prompt on the phone.
* Use a data cable (not charge-only). Check `adb devices -l` in a terminal.
* "PdaNet+ USB Tether is not running": open PdaNet+ on the phone and turn on USB Tether.

## After an unexpected unplug

The app shows **Network needs restoring** with a **Restore network** button (one password prompt).
From a terminal: `sudo /usr/bin/pdanet usb off`.

## Two copies of `pdanet`

If you also have an older `~/.local/bin/pdanet`, your shell may run that one instead of `/usr/bin/pdanet`.
The desktop app always uses `/usr/bin/pdanet`. Disconnect before switching between them.

## Password dialog every time

The polkit action `org.pdanet.desktop.manage` allows the password to be remembered for a few minutes for the
active session. If pkexec does not match the action it falls back to a generic prompt each time; this is safe
but less convenient. Please report which dialog you get.
