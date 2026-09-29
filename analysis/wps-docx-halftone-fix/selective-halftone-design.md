# WPS/DOCX-scoped selective halftone design (offline only)

This design does not install a filter, alter a queue, modify a PPD, change SpliX/SPL3, or print.

## Recommended architecture

`WPS PDF spool → WPS fingerprint + vector object mask → existing geometry normalizer (PATCH-X/PATCH-Y, scale 1.0) → 8-bit grayscale control → authentic Spot CosineDot 106/45° render for target mask → protected-region composite to 1-bit K → unchanged rastertoqpdl → offline SPL3 validation`

The mask is discovered at the PDF/object stage, while the final compositing is performed against the 8-bit-derived geometry. This keeps page placement and the existing control raster authoritative.

## Target and protected objects

Target only neutral, vector, light-gray fills in the measured Day01/WPS range (initially RGB 220–245, with the captured header at RGB 232). The current capture exposes three header rectangles as vector fills. Never target font antialiasing, images, photographs, scanned backgrounds, shadows, fine lines, borders, or any non-neutral color.

Protected pixels are copied byte-for-byte from the Current CoreGraphics control raster. The prototype mask generated here yields protected-region XOR = 0 and changes only pixels inside the three header-fill rectangles.

## Tone and topology separation

This phase does not apply an RGB tone curve or `232→xxx` compensation. The first prototype uses the original semantic gray as the Spot input. Its measured coverage is 6.29% in the allowed fill pixels versus 12.21% for Current, so this topology-only candidate is a diagnostic artifact, not yet a production-ready density match. A separate, explicitly approved second-variable tone calibration is required before any physical regression.

## Safety gates

1. Combined WPS fingerprint confidence HIGH.
2. Exact target mask and protected object mask available.
3. Protected XOR = 0; geometry and Golden PDF unchanged.
4. Coverage difference recorded and within a separately approved tolerance.
5. Unchanged `rastertoqpdl` produces valid A4/600 dpi/simplex SPL3 with compression `0x11`, checksums, UEL, and exact round-trip.
6. Otherwise BYPASS and do not integrate.
