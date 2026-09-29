# WPS spool detector (offline design)

The detector is scoped to the PDF spool received from WPS Direct Print; it does not inspect a `.docx` extension at the CUPS boundary.

## Signals from the captured WPS Day01 spool

- Creator: `WPS Office`
- Title ends in `.docx`
- Producer contains `Quartz PDFContext`
- PDF 1.3, Letter MediaBox/CropBox 612×792 pt
- ICCBased RGB page ColorSpace
- No XObject image; decoded content is a large vector stream
- Repeated vector path/fill operators and an explicit neutral gray `0.9098039 0.9098039 0.9098039 sc` (RGB 232/255)
- WPS application identity: `com.kingsoft.wpsoffice.mac`, version `12.1.26055`

Combined decision: **HIGH confidence (0.98)** for this captured family. No single Producer string is sufficient by itself. The detector must require the combined WPS/Quartz/Letter/ICCBased/vector-gray signals and a valid target object mask.

## False-positive and fallback policy

False-positive risk is **LOW** for the current evidence set. A missing, contradictory, or malformed signal causes **BYPASS**. If the neutral-gray vector object cannot be localized without touching text, rules, images, or shadows, the compatibility layer must also BYPASS. The policy intentionally prefers missing a repair over modifying an ordinary PDF.

Machine-readable signals are in [`wps-fingerprint.json`](wps-fingerprint.json).
