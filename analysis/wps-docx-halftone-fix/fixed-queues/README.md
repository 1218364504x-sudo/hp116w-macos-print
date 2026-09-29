# HP116W fixed queue PPDs

This directory retains the two production PPD sources used by the formal CUPS
queues:

- `HP116W_600dpi.ppd`: Normal, 600 dpi, A4
- `HP116W_1200dpi.ppd`: High, 1200 dpi, A4

Both PPDs reference the installed shared wrapper and `rastertoqpdl`. Their
SHA-256 values are recorded in `FINAL_PRODUCTION_STATUS.md` at the project
root and must match the live `/private/etc/cups/ppd/` files before recovery.
The historical 1200dpi install/recovery scripts are kept locally because they
contain the original LAN endpoint. Their Router/config pins predate the latest
600dpi revision and do not recreate both current queues by themselves. Check
the live queue state and prepare a version-matched installer before recovery.
