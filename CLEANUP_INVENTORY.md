# HP116W Cleanup Inventory

Recorded: 2026-09-14

This inventory covers only the local project directory.
The public repository omits the local-only installer/manifest, Ghostscript
binary bundle, print samples, and device-specific network identifiers.
Counts below are logical inventory entries rather than every file in the
retained runtime trees. The live CUPS installation and printer discovery
entries are outside the project-directory count.

## Summary

```text
KEEP_COUNT=9
DELETED_COUNT=12
REVIEW_COUNT=3
FINAL_PROJECT_SIZE_BEFORE=not recorded before this cleanup turn
FINAL_PROJECT_SIZE_AFTER=187M (du -sh, 2026-09-14)
POST_CLEANUP_QUEUE_CHECK=PASS
SOURCE_LIVE_MATCH=true
HASH_PINS_STATUS=PASS
RETAINED_REFERENCE_CHECK=PASS (32 references)
```

## KEEP

1. `analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/` production
   source, config, manifests, PPD candidates, and install/rollback scripts.
2. `analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/production-runtime/`
   current normalizer, 600/1200 adapters, Ghostscript, and resources.
3. `analysis/wps-docx-halftone-fix/600-cups-runtime-fix/wheels/` runtime wheels
   referenced by the production installer.
4. `analysis/wps-docx-halftone-fix/dev-queue-integration/hp116w_wps_dispatcher.py`
   current dispatcher source.
5. `analysis/wps-docx-halftone-fix/fixed-queues/` the two formal queue PPDs and
   recovery notes.
6. `analysis/openprinting-gray-600/install-generic-600.sh` and its final
   600dpi status document.
7. `analysis/wps-docx-halftone-fix/FINAL_1200_PRODUCTION_STATUS.md` and the
   root `FINAL_PRODUCTION_STATUS.md`.
8. `selective-halftone-design.md`, `wps-detector.md`, and the read-only SPL3
   inspection helper used for final parameter documentation.
9. The four required regression fixture categories: `BAD_SMask`, WPS GUI
   ICCBased, `NORMAL_PDF_NATIVE_BYPASS`, and `WPS_DAY01_HIGH_CONFIDENCE`.

## DELETE completed

The accessible, confirmed-unused project artifacts removed during cleanup
were the development queue `HP116W_600dpi_AB_DEV`, diagnostic route/capture
outputs, spool copies, physical A/B and RGB235 candidate outputs, temporary
rendered raster/QPDL/SPL files, 600/1200 candidate and tone-search outputs,
stale backups and duplicate packages, obsolete queue-adapter material, and
the project `output/` and `tmp/` trees. No live production source, runtime,
PPD, fixture, or recovery script was modified.

## REVIEW / permission-blocked

The following remain review-only. They are either reference material or
confirmed cleanup targets that cannot be removed by the current user because
the directory owner is `root`:

- `analysis/vendor-mac-driver-reference/` (vendor/reference archive).
- `analysis/windows-hp116w-driver-reference/` (historical reference notes).
- Root-owned residual paths:
  `analysis/spool-live-capture`,
  `analysis/openprinting-gray-600/.install-generic-600-backup`,
  `analysis/wps-docx-halftone-fix/fixed-queues/admin-finalize-reports`,
  the three dated directories under
  `analysis/wps-docx-halftone-fix/admin-dev-queue-install/install-records/`,
  `analysis/wps-docx-halftone-fix/1200-admin-runs`, the four
  `physical-send-runs` directories under the old 1200 candidate/calibration/
  tone trees, `local-ipp-front-end/physical-validation-runs`, and
  `native-quality-ui-final/runs`.

The residuals are not referenced by either production queue or by the live
hash-pin chain. They can be removed later by an administrator after a final
path review. A non-destructive `rmdir` probe confirmed that each target still
contains protected content; no `sudo` operation was attempted in this turn.

## Queue result

```text
PRODUCTION_QUEUES=HP116W_600dpi,HP116W_1200dpi
REMOVED_QUEUES=HP116W_600dpi_AB_DEV
PRESERVED_DISCOVERY_ENTRIES=two Bonjour/IPPS entries (device-specific suffixes redacted)
```
