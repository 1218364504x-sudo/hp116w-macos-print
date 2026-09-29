# HP116W Final Production Status

Recorded: 2026-09-15
Snapshot: final A4 WPS/1200 resolution repair install, physical acceptance, and freeze

Public copy: the printer's LAN address and Bonjour discovery suffixes are
redacted. Component hashes and acceptance results are unchanged.

## Latest 600dpi production revision — 2026-09-28

The installed Router and config match the project sources. The 600dpi WPS
`.docx` gray fix passed paper acceptance and is the latest frozen 600dpi
production revision. The 2026-09-15 snapshot below remains the record for the
other frozen components and the 1200dpi route.

```text
600_WPS_DOCX_GRAY_FIX=PASS
600_PRODUCTION_FINAL=PASS
600_PRODUCTION_FROZEN=yes
GENERIC_HIGHLIGHT_A_PATH=PASS
SHADOW_LIGHT_GRAY_PHYSICAL=PASS
PAGE_ORDER_PHYSICAL=PASS
ODD_EVEN_PAGES_PHYSICAL=PASS
PDF_WPS_PREVIOUS_PATHS=NO_ANOMALY_REPORTED
ROUTER_SHA256=33e7c2340719398630916664343855a111b8425f797ae20e336321bbe7db6712
CONFIG_SHA256=5cb6e27aac7227ba2567a184f5888e28bed9b78537adf1380bde55eb07deefef
```

WPS/Quartz recognition passed, but the `.docx` PDF used `0.9294118` and
`0.9568627` light-gray instructions. WPS Selective had no exact target gray,
yet occupied the route and prevented Generic Highlight A. The 600dpi-only
condition now passes WPS PASS jobs with no target-gray page to the existing
Generic classifier. Paper acceptance confirmed the shadow, page order, and
odd/even pages.

## Final decision

```text
FINAL_PRODUCTION_STATUS=PASS
ROOT_CAUSE_1=WPS media detection accepted Letter only; standard A4 was incorrectly BYPASS
ROOT_CAUSE_2=Generic 1200 did not explicitly pass 1200dpi to cgpdftoraster and could receive 600dpi
A4_WPS_DETECT_FIX=PASS
GENERIC_1200_RESOLUTION_FIX=PASS
1200_SHADOW_PHYSICAL=PASS
1200_TRUE_1200=PASS
600_REGRESSION=PASS
SHADOW_FINAL=PASS
MANUAL_DUPLEX_PAGE_ORDER=PASS
600_PRODUCTION_FROZEN=yes
1200_PRODUCTION_FROZEN=yes
SHADOW_FINAL_FROZEN=yes
MANUAL_DUPLEX_PAGE_ORDER_FROZEN=yes
```

The final candidate supports Letter and A4 media with a 1 pt tolerance. The
Generic 1200 path explicitly supplies the PPD-supported 1200dpi quality
parameter and fails closed if the resulting raster is not 1200dpi. pypdf page
selection/order, RGB235, the validated shadow algorithm, and rastertoqpdl were
unchanged.

## Release gates

```text
600_PRODUCTION_FINAL=PASS
600_PRODUCTION_STATUS=PASS
WPS_600_FINAL_PHYSICAL=PASS
600_PRODUCTION_FROZEN=yes

1200_PRODUCTION_FINAL=PASS
1200_PRODUCTION_STATUS=PASS
WPS_1200_FINAL_PHYSICAL=PASS
1200_PRODUCTION_FROZEN=yes
```

The two production routes are frozen. The 600 dpi route retains the validated
Highlight A transfer; the 1200 dpi route uses the independent RGB235 Generic
profile. No further production implementation changes are pending.

## Final pagination and shadow acceptance

```text
INSTALL_STATUS=PASS
CGPDFTOPDF_SHADOW_REGRESSION=CONFIRMED
PAGE_PROCESSOR=pypdf
CGPDFTOPDF_REMOVED_FROM_PAGE_PATH=PASS
PAGE_PROCESSING_ONCE=PASS
600_SHADOW_PHYSICAL=PASS
ODD_NORMAL_PHYSICAL=PASS
ODD_NORMAL=PASS
1200_SHADOW_PHYSICAL=PASS
EVEN_REVERSE_PHYSICAL=PASS
EVEN_REVERSE=PASS
SHADOW_FINAL=PASS
SHADOW_FINAL_FROZEN=yes
MANUAL_DUPLEX_PAGE_ORDER=PASS
MANUAL_DUPLEX_PAGE_ORDER_FROZEN=yes
```

The original shadow regression was caused by `cgpdftopdf` rewriting WPS PDF
page media and metadata, which downgraded WPS selective detection. The native
stage was removed from the production page path. The pinned `pypdf` runtime now
performs the single page selection/order step without rasterization, flattening,
color conversion, scaling, or page-size changes.

```text
FINAL_PIPELINE=SOURCE PDF -> minimal pypdf page select/reorder -> wrapper/router -> existing cgpdftoraster / Generic / WPS rendering -> existing rastertoqpdl -> printer
```

## Production queues

```text
FORMAL_QUEUE_COUNT=2
FORMAL_QUEUES=HP116W_600dpi,HP116W_1200dpi
HP116W_600dpi_PPD=/private/etc/cups/ppd/HP116W_600dpi.ppd
HP116W_600dpi_URI=socket://<printer-ip>:9100
HP116W_600dpi_STATE=enabled,accepting,idle,pending=0
HP116W_600dpi_DEFAULT_QUALITY=Normal
HP116W_600dpi_DEFAULT_RESOLUTION=600dpi

HP116W_1200dpi_PPD=/private/etc/cups/ppd/HP116W_1200dpi.ppd
HP116W_1200dpi_URI=socket://<printer-ip>:9100
HP116W_1200dpi_STATE=enabled,accepting,idle,pending=0
HP116W_1200dpi_DEFAULT_QUALITY=High
HP116W_1200dpi_DEFAULT_RESOLUTION=1200dpi

SYSTEM_DEFAULT_PRINTER=HP116W_600dpi
```

The CUPS inventory also contains two automatic Bonjour/IPPS discovery names
(one local `lpstat -p` entry and one discovery-only `lpstat -e` entry; their
device-specific suffixes are redacted in this public copy). They are
outside this project and were intentionally left untouched. The project-created
`HP116W_600dpi_AB_DEV` queue was removed.

## Frozen route parameters

```text
600_ROUTE=WPS_SELECTIVE_600 plus GENERIC_HIGHLIGHT_A fallback
600_INPUT_RGB=190
600_SCREEN=CosineDot 106.17 LPI / 45 degrees
600_RASTER=600x600dpi Gray 1-bit

1200_ROUTE=WPS_SELECTIVE_1200 plus GENERIC_RGB235_1200 fallback
1200_INPUT_RGB=235
1200_SCREEN=CosineDot 106.17 LPI / 45 degrees
1200_RASTER=1200x1200dpi Gray 1-bit
1200_TRANSFER=none
```

## 2026-09-15 production SHA-256 snapshot

| Component | Path | SHA-256 |
| --- | --- | --- |
| wrapper | `/usr/libexec/cups/filter/hp116w_smart_cups_filter` | `24f30f87970a35f7967e69d33081914d1de0221537ac7316c839157b645c4e88` |
| router | `/usr/libexec/cups/filter/hp116w_smart_router` | `51686bd98815a135f2a8019848252ee613fee8b410c4342eaa59c33bddcbf623` |
| router config | `/usr/libexec/cups/filter/smart-router-config.json` | `b31b77e4f7abe3227f1f64beb5256055fe006957ec0e95e05288c80273997fa6` |
| dispatcher | `/usr/libexec/cups/filter/hp116w_wps_dispatcher` | `0e40e04e71fdd3605a091c100d2d1cc53a50344248ec0d3ce178ab1fd9c288bf` |
| generic 600 adapter | `/Library/Application Support/HP116W/runtime/hp116w_generic_600.py` | `311dc1c403f1a0ebb223f5323729ff1b1cd2d532f2cbb8b76c71ebffc4245e29` |
| generic 1200 adapter | `/Library/Application Support/HP116W/runtime/hp116w_generic_1200.py` | `7c9829a8f049546426596132fcd5d7b70bb4aa22d257cb7836df0339430f2fe3` |
| rastertoqpdl | `/usr/libexec/cups/filter/rastertoqpdl` | `d2929bac0adee4fda83bd601fa84c219cff5891a7ffaff3414f22a99101dd4e5` |
| 600 PPD | `/private/etc/cups/ppd/HP116W_600dpi.ppd` | `995c0dd606f6f05f4328916cffd87c8d2ccf010fae5c6e463a5613b94a588495` |
| 1200 PPD | `/private/etc/cups/ppd/HP116W_1200dpi.ppd` | `3b2234e66391f323e7420796d00239f4a5dfcf0a24606d48799a69818c95f1e9` |

The installed production config pins all nine live components above plus the
unchanged native `cgpdftoraster`, Ghostscript, and baseline PPD. The page
processor is the deployed pinned `pypdf` 6.14.2 runtime. A direct hash
comparison reported:

```text
CONFIG_PIN_MATCH=true
LIVE_CANDIDATE_MATCH=true
PPYDF_RUNTIME_UNCHANGED=true
RASTERTOQPDL_UNCHANGED=true
CGPDFTORASTER_UNCHANGED=true
1200_TRUE_1200_RASTER=PASS (9500x13617, 1188 bytes/line)
A4_WPS_DETECTED=YES
WPS_SELECTIVE_1200=YES
RGB235_ACTIVE=YES
GENERIC_1200_TRUE_1200=YES
600_ROUTE_UNCHANGED=YES
```

## Physical acceptance

```text
HP116W_1200dpi=PASS
1200_SHADOW_PHYSICAL=PASS
1200_TRUE_1200=PASS
HP116W_600dpi=PASS
600_REGRESSION=PASS
ODD_NORMAL=PASS
EVEN_REVERSE=PASS
```

`HP116W_SPLIX_1200_TEST` remains an independent experiment. Its queue,
configuration, files, and `rastertoqpdl_splix_test` were not used for or
merged into production.

The project-side sources matching the live chain are kept under
`analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/`, with the production
dispatcher source at `dev-queue-integration/hp116w_wps_dispatcher.py`.

## Cleanup result

```text
FINAL_CLEANUP=PASS
DELETED_PROJECT_TEST_QUEUE=HP116W_600dpi_AB_DEV
DELETED_PROJECT_TEMP_ARTIFACTS=accessible confirmed diagnostic/capture/spool/physical-A-B/candidate outputs
ROOT_OWNED_TEMP_RESIDUALS=documented; not writable by current user
PRESERVED_PRODUCTION_CHAIN=yes
PRESERVED_REQUIRED_FIXTURES=yes
```

The retained project content is limited to production sources/configuration,
install and rollback material, the two PPDs, runtime wheels, final status and
parameter notes, and the `BAD_SMask`, WPS GUI ICCBased, NORMAL_IMAGE, and
WPS_SELECTIVE regression fixtures. Vendor/reference material and root-owned
rollback/evidence directories remain review-only and were not altered.

## Cleanup inventory and permission boundary

The detailed KEEP/DELETE/REVIEW inventory is recorded in
`CLEANUP_INVENTORY.md`. Its counts are logical inventory entries, not the
individual files inside the retained Ghostscript/runtime trees:

```text
KEEP_COUNT=9
DELETED_COUNT=12
REVIEW_COUNT=3
FINAL_PROJECT_SIZE_AFTER=187M (du -sh, 2026-09-14)
POST_CLEANUP_QUEUE_CHECK=PASS
SOURCE_LIVE_MATCH=true
HASH_PINS_STATUS=PASS
RETAINED_REFERENCE_CHECK=PASS (32 references)
```

All accessible DELETE candidates were removed. The following confirmed
project-only cleanup targets remain because they are owned by `root` and are
not writable by the current user:

```text
analysis/spool-live-capture
analysis/openprinting-gray-600/.install-generic-600-backup
analysis/wps-docx-halftone-fix/fixed-queues/admin-finalize-reports
analysis/wps-docx-halftone-fix/admin-dev-queue-install/install-records/20260903-222738
analysis/wps-docx-halftone-fix/admin-dev-queue-install/install-records/20260903-223636
analysis/wps-docx-halftone-fix/admin-dev-queue-install/install-records/20260903-224326
analysis/wps-docx-halftone-fix/1200-admin-runs
analysis/wps-docx-halftone-fix/1200-final-candidate-rgb235/physical-send-runs
analysis/wps-docx-halftone-fix/1200-physical-calibration-package/physical-send-runs
analysis/wps-docx-halftone-fix/1200-tone-extension-210-240/physical-send-runs
analysis/wps-docx-halftone-fix/1200-tone-refinement-233-237/physical-send-runs
analysis/wps-docx-halftone-fix/local-ipp-front-end/physical-validation-runs
analysis/wps-docx-halftone-fix/native-quality-ui-final/runs
```

These paths are review-only residuals and do not participate in either live
production route. A non-destructive `rmdir` probe confirmed that they still
contain protected content, so no further cleanup was attempted without
administrator authority.
