# HP116W 1200dpi Production Final Status

Recorded: 2026-09-15

```text
1200_PRODUCTION_ROUTE=FINAL
1200_PRODUCTION_FINAL=PASS
FINAL_PRODUCTION_STATUS=PASS
1200_PRODUCTION_STATUS=PASS
WPS_1200_FINAL_PHYSICAL=PASS
LOW_GRAY_SHADOW=PASS
BLACK_TEXT=PASS
LAYOUT=PASS
1200_SHADOW_PHYSICAL=PASS
1200_TRUE_1200=PASS
1200_EVEN_REVERSE_PHYSICAL=PASS
SHADOW_FINAL=PASS
SHADOW_FINAL_FROZEN=yes
MANUAL_DUPLEX_PAGE_ORDER=PASS
MANUAL_DUPLEX_PAGE_ORDER_FROZEN=yes
1200_PRODUCTION_FROZEN=yes
A4_WPS_DETECT_FIX=PASS
GENERIC_1200_RESOLUTION_FIX=PASS
WPS_A4_DETECTED=YES
WPS_SELECTIVE_1200=YES
RGB235_ACTIVE=YES
PAGE_PROCESSOR=pypdf
CGPDFTOPDF_SHADOW_REGRESSION=CONFIRMED
CGPDFTOPDF_REMOVED_FROM_PAGE_PATH=PASS
PAGE_PROCESSING_ONCE=PASS

600_PRODUCTION_FINAL=PASS
600_PRODUCTION_FROZEN=yes
600_REGRESSION=PASS
600_ROUTE_UNCHANGED=YES
```

## Root cause and final repair

```text
ROOT_CAUSE_1=WPS media detector accepted Letter only; standard A4 was BYPASS
ROOT_CAUSE_2=Generic 1200 omitted an explicit 1200dpi renderer parameter and could receive 600dpi
A4_WPS_DETECT_FIX=PASS (Letter/A4 with 1 pt tolerance)
GENERIC_1200_RESOLUTION_FIX=PASS (Quality/cupsPrintQuality/Resolution=1200dpi)
GENERIC_1200_FAIL_CLOSED=YES
```

The pypdf page-selection/order step, RGB235 value, validated shadow algorithm,
600dpi production algorithm, and rastertoqpdl were not changed.

## Production queue and gate

```text
QUEUE=HP116W_1200dpi
1200_GATE=queue identity HP116W_1200dpi, unless explicit 600dpi conflict
```

The dedicated `HP116W_1200dpi` queue is authoritative when an application
omits Resolution/Quality options. An explicit conflicting 600dpi
`Resolution`/`Quality` remains fail-closed and does not force the 1200 route.
The `HP116W_600dpi` queue and its frozen gate are unchanged.

## Final route and classifier

```text
WPS_SELECTIVE high confidence
  -> WPS_SELECTIVE_1200

VECTOR_TEXT_SMask
  -> GENERIC_RGB235_1200

ICCBased_IMAGE_HEAVY with Creator starting "WPS Office"
and Producer containing "Quartz PDFContext"
  -> GENERIC_RGB235_1200

ordinary ICCBased_IMAGE_HEAVY
  -> NATIVE_BYPASS

AMBIGUOUS / ERROR
  -> NATIVE_BYPASS
```

The WPS/Quartz exception is narrow. Ordinary ICCBased image-heavy documents
remain on Native, and WPS_SELECTIVE keeps priority over Generic routing.

## 1200 Generic renderer

```text
Tone input: RGB235 only
Halftone: CosineDot
Screen: 106.17 LPI / 45 degrees
Raster: 1200x1200dpi, Gray, 1-bit
Transfer: none
```

The 1200 Generic path does not use the 600dpi Highlight A transfer. The
validated WPS production print produced normal light-gray shadow coverage,
black text, concentration, and layout.

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
WPS -> HP116W_1200dpi: PASS
WPS_A4_DETECTED: PASS
WPS_SELECTIVE_1200: PASS
RGB235_ACTIVE: PASS
GENERIC_1200_TRUE_1200: PASS (9500x13617, 1188 bytes/line)
LOW_GRAY_SHADOW: PASS
BLACK_TEXT: PASS
LAYOUT: PASS
1200_TRUE_1200: PASS
600_REGRESSION: PASS
ODD_NORMAL: PASS
EVEN_REVERSE: PASS
```

## Live production integrity

```text
Wrapper SHA256=24f30f87970a35f7967e69d33081914d1de0221537ac7316c839157b645c4e88
Router SHA256=51686bd98815a135f2a8019848252ee613fee8b410c4342eaa59c33bddcbf623
Dispatcher SHA256=0e40e04e71fdd3605a091c100d2d1cc53a50344248ec0d3ce178ab1fd9c288bf
Config SHA256=b31b77e4f7abe3227f1f64beb5256055fe006957ec0e95e05288c80273997fa6
Generic 1200 SHA256=7c9829a8f049546426596132fcd5d7b70bb4aa22d257cb7836df0339430f2fe3
rastertoqpdl SHA256=d2929bac0adee4fda83bd601fa84c219cff5891a7ffaff3414f22a99101dd4e5
PPD SHA256=26b58352a18f4424988c3a90939369640b286e309e22ee975516a83dcd88f386
DeviceURI=socket://<printer-ip>:9100
HP116W_1200dpi_QUEUE=enabled,accepting,idle
HP116W_600dpi_QUEUE=enabled,accepting,idle
PPYDF_RUNTIME=UNCHANGED
CGPDFTORASTER_SHA256=7b0ab7ad0a10119123bbf47addb04801f896d494959632a27b22b86a68a1ff2b
HASH_PINS_STATUS=PASS
```

No 600dpi production logic, PPD, DeviceURI, pypdf page-order logic, RGB235,
shadow algorithm, or rastertoqpdl was changed by this finalization. The
1200dpi production state is frozen.
