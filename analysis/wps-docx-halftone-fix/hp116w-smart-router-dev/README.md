# HP116W production source bundle

This public directory retains source and configuration for the live HP116W
production chain. Installed components are protected by the SHA-256 pins in
`smart-router-config.json`. The original historical installer, rollback script,
and `production-manifest.json` contain a machine-specific LAN endpoint and
remain local. The validated Ghostscript binary/resources also remain local
until their public redistribution provenance is established. Consequently this
directory alone is not a complete reinstall package.

## Production chain

```text
PDF -> pypdf page select/reorder -> hp116w_smart_cups_filter -> hp116w_smart_router
    -> WPS dispatcher or native cgpdftoraster
    -> rastertoqpdl -> SPL3
```

The native `cgpdftopdf` stage is deliberately excluded. Its PDF rewrite changed
WPS source media/metadata and caused a confirmed shadow regression. The wrapper
uses the pinned `pypdf` runtime for the single page-ranges/page-set/order step;
when no page operation is requested, it passes the original PDF through without
rewriting it. The page processor never rasterizes, flattens, rescales, rotates,
or converts color.

The 600 dpi adapter is the frozen Highlight A route (`RGB190`). The 1200 dpi
adapter is the frozen RGB235-only Generic route (`CosineDot`, 106.17 LPI,
45 degrees, 1200x1200 dpi, Gray 1-bit). Neither adapter invokes a backend or
opens the printer socket.

## Recovery

The local-only `install-production-smart-router.sh` is the historical
administrator-only 1200dpi install/reinstall entry point. Its Router/config
pins predate the 2026-09-28 frozen 600dpi revision, so it cannot reinstall the
latest two-queue state without a separately reviewed, synchronized manifest
and release package. The local-only rollback script applies to backups made
by its matching installer.

`HP116W_High_Quality_SMART_CANDIDATE.ppd` and
`HP116W_High_Quality_NATIVE.ppd` are retained as the 1200 candidate and native
baseline source files. The live fixed queue PPDs are kept separately under
`../fixed-queues/`.

## Regression fixtures

`test-fixtures/` contains local samples used for checks, but the PDFs are
excluded from the GitHub repository because their print content and metadata
have not been cleared for upload:

- `BAD_SMask.pdf`
- `WPS_DAY01_HIGH_CONFIDENCE.pdf`
- `NORMAL_PDF_NATIVE_BYPASS.pdf`

The WPS GUI ICCBased fixture remains at
`../openprinting-gray-600/fixtures/test/WPS_GUI_DAY01_PAGE1_ICCBASED.pdf`.
