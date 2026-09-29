#!/usr/bin/env python3
"""Read-only SPL3/QPDL capture inspector.

The input is opened read-only and is never rewritten. JSON is emitted only to
stdout. The tool reports framing, PJL controls, QPDL page headers, resolutions,
encoded band geometry, compression, and checksums. It deliberately does not
claim that physical print quality can be inferred from a spool stream alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


UEL = b"\x1b%-12345X"
QPDL_MARKER = b"ENTER LANGUAGE = QPDL"
V3_SIGNATURE = b"\xef\xcd\xab\x09"
PAPER_NAMES = {2: "A4"}


class AnalysisError(ValueError):
    pass


def u16be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def u32be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def read_only_snapshot(path: Path) -> Tuple[bytes, Dict[str, Any]]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AnalysisError("input is not a regular file")
        chunks: List[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise AnalysisError("input changed while it was being read")
    if len(data) != info.st_size:
        raise AnalysisError("short read while inspecting input")
    return data, {
        "device": info.st_dev,
        "inode": info.st_ino,
        "size_bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode_octal": oct(stat.S_IMODE(info.st_mode)),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def pjl_values(lines: List[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in lines:
        match = re.match(r"@PJL\s+(?:SET|DEFAULT)\s+([A-Za-z0-9_-]+)\s*=\s*(.*)$", line)
        if match:
            values[match.group(1).upper()] = match.group(2).strip().strip('"')
    return values


def parse_spl3(raw: bytes) -> Dict[str, Any]:
    marker = raw.find(QPDL_MARKER)
    if marker < 0:
        raise AnalysisError("missing '@PJL ENTER LANGUAGE = QPDL' marker")
    body_start = raw.find(b"\n", marker)
    if body_start < 0:
        raise AnalysisError("unterminated QPDL PJL line")
    body_start += 1
    body_end = raw.rfind(UEL)
    if body_end < body_start:
        raise AnalysisError("missing final UEL")
    body = raw[body_start:body_end]
    if not body or body[-1:] != b"\x09":
        raise AnalysisError("missing QPDL document trailer 0x09")

    prefix = raw[:body_start].replace(UEL, b"")
    pjl_lines = [
        line.decode("ascii", errors="replace")
        for line in prefix.splitlines()
        if line.startswith(b"@PJL")
    ]
    settings = pjl_values(pjl_lines)
    cursor = 0
    pages: List[Dict[str, Any]] = []
    checksum_failures: List[Dict[str, int]] = []

    while cursor < len(body) - 1:
        page_offset = cursor
        if body[cursor] != 0 or cursor + 0x11 > len(body):
            raise AnalysisError(f"expected QPDL page header at body offset {cursor}")
        header = body[cursor : cursor + 0x11]
        cursor += 0x11
        resolution_x = header[0x10] * 100
        resolution_y = header[0x01] * 100
        width_300 = u16be(header, 5)
        height_300 = u16be(header, 7)
        page: Dict[str, Any] = {
            "number": len(pages) + 1,
            "body_offset": page_offset,
            "raw_header_hex": header.hex(" "),
            "resolution_dpi": [resolution_x, resolution_y],
            "is_600dpi": resolution_x == 600 and resolution_y == 600,
            "is_1200dpi": resolution_x == 1200 and resolution_y == 1200,
            "copies": u16be(header, 2),
            "paper_code": header[4],
            "paper": PAPER_NAMES.get(header[4], "unknown"),
            "page_extent_at_300dpi_px": [width_300, height_300],
            "page_extent_at_declared_resolution_px": [
                width_300 * resolution_x // 300,
                height_300 * resolution_y // 300,
            ],
            "paper_source": header[9],
            "duplex_header_value": header[0x0B],
            "tumble_header_value": header[0x0C],
            "qpdl_version": header[0x0E],
            "bands": [],
        }
        while cursor < len(body):
            record = body[cursor]
            if record == 0x0C:
                if cursor + 11 > len(body):
                    raise AnalysisError("truncated QPDL band header")
                number = body[cursor + 1]
                width = u16be(body, cursor + 2)
                height = u16be(body, cursor + 4)
                compression = body[cursor + 6]
                payload_size = u32be(body, cursor + 7)
                start = cursor + 11
                end = start + payload_size
                if end > len(body):
                    raise AnalysisError(f"band {number} payload is truncated")
                payload = body[start:end]
                signature_ok = len(payload) >= 8 and payload[:4] == V3_SIGNATURE
                given = u32be(payload, len(payload) - 4) if len(payload) >= 4 else -1
                calculated = (
                    (sum(payload[:4]) + sum(payload[4:-4])) & 0xFFFFFFFF
                    if len(payload) >= 8
                    else -1
                )
                checksum_ok = signature_ok and given == calculated
                band = {
                    "number": number,
                    "width_px": width,
                    "height_px": height,
                    "vertical_extent_px": [number * height, (number + 1) * height],
                    "compression": f"0x{compression:02x}",
                    "compression_name": "SPL3 0x11 bilevel" if compression == 0x11 else "unknown",
                    "payload_size_bytes": payload_size,
                    "compressed_plane_bytes": max(0, payload_size - 8),
                    "signature_hex": payload[:4].hex(" ") if len(payload) >= 4 else "",
                    "signature_ok": signature_ok,
                    "checksum": given,
                    "calculated_checksum": calculated,
                    "checksum_ok": checksum_ok,
                }
                page["bands"].append(band)
                if not checksum_ok:
                    checksum_failures.append({"page": page["number"], "band": number})
                cursor = end
                continue
            if record == 0x01:
                if cursor + 3 > len(body):
                    raise AnalysisError("truncated QPDL page footer")
                page["footer_hex"] = body[cursor : cursor + 3].hex(" ")
                cursor += 3
                break
            raise AnalysisError(f"unexpected byte 0x{record:02x} at QPDL body offset {cursor}")
        else:
            raise AnalysisError("QPDL page has no footer")

        bands = page["bands"]
        page["encoded_band_geometry"] = {
            "nonempty_band_count": len(bands),
            "band_widths_px": sorted({band["width_px"] for band in bands}),
            "band_heights_px": sorted({band["height_px"] for band in bands}),
            "nonempty_vertical_extent_px": (
                [
                    min(band["vertical_extent_px"][0] for band in bands),
                    max(band["vertical_extent_px"][1] for band in bands),
                ]
                if bands
                else None
            ),
        }
        pages.append(page)

    if cursor != len(body) - 1:
        raise AnalysisError("unexpected bytes before QPDL trailer")
    resolutions = sorted({tuple(page["resolution_dpi"]) for page in pages})
    all_bands = [band for page in pages for band in page["bands"]]
    explicit_halftone = [
        line for line in pjl_lines if re.search(r"HALFTONE|SCREEN|GAMMA", line, re.IGNORECASE)
    ]
    return {
        "format": "SPL3/QPDL",
        "valid": bool(pages) and not checksum_failures,
        "framing": {
            "pjl_qpdl_marker": True,
            "body_offset": body_start,
            "body_size_bytes": len(body),
            "document_trailer_hex": "09",
            "final_uel": True,
        },
        "pjl_lines": pjl_lines,
        "pjl_settings": settings,
        "page_count": len(pages),
        "resolution": {
            "values_dpi": [list(value) for value in resolutions],
            "all_pages_600dpi": bool(pages) and all(page["is_600dpi"] for page in pages),
            "all_pages_1200dpi": bool(pages) and all(page["is_1200dpi"] for page in pages),
            "contains_600dpi": any(page["is_600dpi"] for page in pages),
            "contains_1200dpi": any(page["is_1200dpi"] for page in pages),
        },
        "pages": pages,
        "compression_codes": sorted({band["compression"] for band in all_bands}),
        "checksum_failures": checksum_failures,
        "halftone_related": {
            "density": settings.get("DENSITY"),
            "ret": settings.get("RET"),
            "paper_type": settings.get("PAPERTYPE"),
            "explicit_halftone_or_gamma_pjl": explicit_halftone,
            "bilevel_spl3_band_encoding": bool(all_bands)
            and all(band["compression"] == "0x11" for band in all_bands),
            "interpretation_limit": (
                "DENSITY/RET and bilevel bands are observable. The upstream screening algorithm, "
                "screen frequency/angle, and gamma are not named by this payload and cannot be "
                "proven without raster/source correlation or physical measurement."
            ),
        },
    }


def analyze(path: Path) -> Dict[str, Any]:
    before_data, before = read_only_snapshot(path)
    parsed = parse_spl3(before_data)
    after_data, after = read_only_snapshot(path)
    unchanged = (
        before["device"] == after["device"]
        and before["inode"] == after["inode"]
        and before["size_bytes"] == after["size_bytes"]
        and before["mtime_ns"] == after["mtime_ns"]
        and before["sha256"] == after["sha256"]
        and before_data == after_data
    )
    if not unchanged:
        raise AnalysisError("input changed during analysis")
    return {
        "tool_mode": "read-only",
        "path": str(path.resolve()),
        "file_size_bytes": before["size_bytes"],
        "sha256": before["sha256"],
        "mode_octal": before["mode_octal"],
        "input_content_size_mtime_unchanged": True,
        **parsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="captured SPL3/QPDL payload; never modified")
    args = parser.parse_args()
    try:
        result = analyze(args.payload)
    except (OSError, AnalysisError) as exc:
        print(
            json.dumps(
                {"valid": False, "path": str(args.payload), "error": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
