# HP116W 600dpi Production Final Status

Recorded: 2026-09-15

## Latest 600dpi production revision — 2026-09-28

The installed Router and config match the project sources byte for byte. This
revision supersedes the Router and config hashes in the 2026-09-15 snapshot
below; all other frozen components and parameters remain at that snapshot.

```text
600_WPS_DOCX_GRAY_FIX=PASS
600_PRODUCTION_FINAL=PASS
600_PRODUCTION_FROZEN=yes
GENERIC_HIGHLIGHT_A_PATH=PASS
SHADOW_LIGHT_GRAY_PHYSICAL=PASS
PAGE_ORDER_PHYSICAL=PASS
ODD_EVEN_PAGES_PHYSICAL=PASS
PDF_WPS_PREVIOUS_PATHS=NO_ANOMALY_REPORTED
Router SHA256=33e7c2340719398630916664343855a111b8425f797ae20e336321bbe7db6712
Config SHA256=5cb6e27aac7227ba2567a184f5888e28bed9b78537adf1380bde55eb07deefef
```

WPS/Quartz detection passed for the `.docx` print. Its PDF used light-gray
instructions such as `0.9294118` and `0.9568627`, while WPS Selective matched
the exact `0.9098039` gray target. With no target-gray page, WPS Selective
still took the route and prevented Generic Highlight A from running. The
600dpi-only fix sends a WPS PASS job with no target-gray page to the existing
Generic classifier. Paper acceptance confirmed recovered shadow/light gray,
page order, and odd/even pages. The existing PDF/WPS paths showed no anomaly.

The material below records the 2026-09-15 production snapshot.

```text
600_PRODUCTION_ROUTE=FINAL
600_PRODUCTION_FINAL=PASS
600_PRODUCTION_STATUS=PASS
FINAL_PRODUCTION_STATUS=PASS
600_REGRESSION=PASS
WPS_600_FINAL_PHYSICAL=PASS
600_SHADOW_PHYSICAL=PASS
600_ODD_NORMAL_PHYSICAL=PASS
ODD_NORMAL=PASS
SHADOW_FINAL=PASS
SHADOW_FINAL_FROZEN=yes
600_PRODUCTION_FROZEN=yes
PAGE_PROCESSOR=pypdf
CGPDFTOPDF_SHADOW_REGRESSION=CONFIRMED
CGPDFTOPDF_REMOVED_FROM_PAGE_PATH=PASS
PAGE_PROCESSING_ONCE=PASS
MANUAL_DUPLEX_PAGE_ORDER=PASS
MANUAL_DUPLEX_PAGE_ORDER_FROZEN=yes
A4_WPS_DETECT_FIX=PASS
GENERIC_1200_RESOLUTION_FIX=PASS
600_ROUTE_UNCHANGED=YES
```

## Final production route and classifier

The fixed `HP116W_600dpi` queue uses the existing `WPS_SELECTIVE` path first.
If that high-confidence path does not pass, the production structure classifier
uses these rules:

```text
VECTOR_TEXT_SMask
  -> GENERIC_HIGHLIGHT_A

ICCBased_IMAGE_HEAVY with Creator starting "WPS Office"
and Producer containing "Quartz PDFContext"
  -> GENERIC_HIGHLIGHT_A

ordinary ICCBased_IMAGE_HEAVY
  -> NATIVE_BYPASS

AMBIGUOUS / ERROR
  -> NATIVE_BYPASS
```

The WPS/Quartz rule is narrow and does not route ordinary ICCBased image-heavy
documents through Generic. The original high-confidence `WPS_SELECTIVE` path
is unchanged.

The 600dpi Generic path retains the validated Highlight A parameters:

```text
Resolution: 600dpi
Transfer: Ghostscript direct transfer, Highlight A
CosineDot: 106.17 LPI / 45 degrees
Raster: 1-bit Gray CUPS Raster
```

The `HP116W_1200dpi` queue remains on its original route and is not affected by
the 600dpi Generic gate.

## Final pagination path

The native `cgpdftopdf` stage caused a confirmed WPS shadow regression by
rewriting page media and metadata. It is removed from the production path.
The pinned `pypdf` runtime performs page selection and order once, before the
unchanged WPS/Generic renderer.

```text
SOURCE PDF -> minimal pypdf page select/reorder -> wrapper/router -> existing cgpdftoraster / Generic / WPS rendering -> rastertoqpdl -> printer
```

## Physical validation

```text
CLI original PDF: PASS
WPS regenerated PDF (WPS Office / Quartz PDFContext): PASS
LOW_GRAY_SHADOW: PASS
BLACK_TEXT: PASS
LAYOUT: PASS
```

## 2026-09-15 production integrity snapshot

The installed production files match the current source/config files byte for
byte:

```text
Router SHA256=51686bd98815a135f2a8019848252ee613fee8b410c4342eaa59c33bddcbf623
Wrapper SHA256=24f30f87970a35f7967e69d33081914d1de0221537ac7316c839157b645c4e88
Config SHA256=b31b77e4f7abe3227f1f64beb5256055fe006957ec0e95e05288c80273997fa6
Generic adapter SHA256=311dc1c403f1a0ebb223f5323729ff1b1cd2d532f2cbb8b76c71ebffc4245e29
Dispatcher SHA256=0e40e04e71fdd3605a091c100d2d1cc53a50344248ec0d3ce178ab1fd9c288bf
600 PPD SHA256=995c0dd606f6f05f4328916cffd87c8d2ccf010fae5c6e463a5613b94a588495
rastertoqpdl SHA256=d2929bac0adee4fda83bd601fa84c219cff5891a7ffaff3414f22a99101dd4e5
pypdf_RUNTIME=UNCHANGED
HP116W_600dpi_QUEUE=enabled,accepting,idle
HP116W_600dpi_DEVICE_URI=socket://<printer-ip>:9100
```

`Highlight A`, the renderer, PPD, `rastertoqpdl`, and the 1200dpi path were not
changed by this finalization. No further 600dpi production changes are pending.
