#!/usr/bin/env python3
"""Production 600 dpi generic route for the HP116W smart filter.

This module is loaded only by ``hp116w_smart_router`` after the legacy WPS
detector has declined a job.  It keeps the conservative document classifier
used by the isolated 600 dpi validation and renders the safe vector/text path
with the validated Ghostscript transfer and CosineDot screen.  Image-heavy,
ambiguous, or unsupported documents are reported as native so the caller can
fall back to ``cgpdftoraster`` without changing the established native path.
"""
from __future__ import annotations

import os
import json
import re
import signal
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RUNTIME_ROOT = Path(__file__).resolve().parent
SITE_PACKAGES = RUNTIME_ROOT / "site-packages"
if SITE_PACKAGES.is_dir() and str(SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SITE_PACKAGES))

try:
    import numpy as np
    from pypdf import PdfReader
except Exception as exc:  # pragma: no cover - surfaced as a router fallback
    raise RuntimeError(f"generic runtime dependency unavailable: {exc}") from exc


DPI = 600
FULL_W, FULL_H = 4961, 7016
CONTENT_W, CONTENT_H = 4750, 6808
IMAGEABLE_X = IMAGEABLE_Y = round(12.5 * DPI / 72)
RASTER_MAGICS = {b"RaSt", b"tSaR", b"RaS2", b"2SaR", b"RaS3", b"3SaR"}
HEADER_SIZES = {b"RaSt": 420, b"tSaR": 420,
                b"RaS2": 1800, b"2SaR": 1800,
                b"RaS3": 1800, b"3SaR": 1800}
GRAY_TOKEN = b"0.9098039 0.9098039 0.9098039 sc"

HALFTONE_SETUP = (
    "<< /HalftoneType 1 /Frequency 106.17 /Angle 45 "
    "/SpotFunction {180 mul cos exch 180 mul cos add 2 div} >> "
    "/Default exch /Halftone defineresource sethalftone"
)
HIGHLIGHT_A_TRANSFER = (
    "{ dup 0.78 le { } { "
    "dup 0.86 le { 0.78 sub 0.25 mul 0.78 add } { "
    "dup 0.925 le { 0.86 sub 0.6153846 mul 0.80 add } { "
    "dup 0.96 le { 0.925 sub 1.7142857 mul 0.84 add } { "
    "0.96 sub 2.5 mul 0.90 add } ifelse } ifelse } ifelse "
    "} ifelse } settransfer"
)

NON_IMAGE_PAINT_OPERATOR_RE = re.compile(
    rb"(?<![A-Za-z0-9*'])(?:BT|ET|Tf|Tj|TJ|Td|TD|Tm|T\*|m|l|c|v|y|h|re|S|s|f|F|f\*|"
    rb"B|b|B\*|n|W|W\*|sc|SC|scn|SCN|g|G|rg|RG|k|K|cs|CS|sh)"
    rb"(?![A-Za-z0-9*'])"
)
INLINE_IMAGE_RE = re.compile(rb"(?<![A-Za-z0-9*'])(?:BI|ID|EI)(?![A-Za-z0-9*'])")


def deref(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value


def contains_pdf_name(value: Any, name: str) -> bool:
    value = deref(value)
    if isinstance(value, (list, tuple)):
        return any(contains_pdf_name(item, name) for item in value)
    if hasattr(value, "values"):
        return any(contains_pdf_name(item, name) for item in value.values())
    return str(value) == name


def content_signal_counts(data: bytes) -> tuple[int, int]:
    return (len(NON_IMAGE_PAINT_OPERATOR_RE.findall(data)),
            len(INLINE_IMAGE_RE.findall(data)))


def pdf_features(source: Path) -> dict[str, Any]:
    reader = PdfReader(str(source), strict=False)
    pages: list[dict[str, Any]] = []
    totals = {
        "image_xobjects": 0,
        "xobjects": 0,
        "extgstates": 0,
        "smask_entries": 0,
        "alpha_entries": 0,
        "groups": 0,
        "shadings": 0,
        "iccbased_image_xobjects": 0,
        "image_xobject_pages": 0,
        "image_dominant_pages": 0,
        "ambiguous_image_pages": 0,
    }
    for index, page in enumerate(reader.pages, 1):
        resources = deref(page.get("/Resources", {})) or {}
        xobjects = deref(resources.get("/XObject", {})) if hasattr(resources, "get") else {}
        extgstates = deref(resources.get("/ExtGState", {})) if hasattr(resources, "get") else {}
        shadings = deref(resources.get("/Shading", {})) if hasattr(resources, "get") else {}
        contents = page.get_contents()
        content_data = contents.get_data() if contents is not None else b""
        non_image_paint_ops, inline_image_markers = content_signal_counts(content_data)
        image_count = iccbased_image_count = smask_count = non_image_xobjects = 0
        image_details: list[dict[str, Any]] = []
        for value in xobjects.values() if hasattr(xobjects, "values") else ():
            obj = deref(value)
            if not hasattr(obj, "get"):
                continue
            if str(obj.get("/Subtype", "")) == "/Image":
                image_count += 1
                iccbased = contains_pdf_name(obj.get("/ColorSpace"), "/ICCBased")
                if iccbased:
                    iccbased_image_count += 1
                image_details.append({
                    "width": int(obj.get("/Width", 0) or 0),
                    "height": int(obj.get("/Height", 0) or 0),
                    "colorspace_iccbased": iccbased,
                    "has_smask": obj.get("/SMask") is not None,
                })
            else:
                non_image_xobjects += 1
            if obj.get("/SMask") is not None:
                smask_count += 1
        alpha_count = 0
        for value in extgstates.values() if hasattr(extgstates, "values") else ():
            obj = deref(value)
            if not hasattr(obj, "get"):
                continue
            if obj.get("/SMask") is not None:
                smask_count += 1
            for key in ("/ca", "/CA"):
                if obj.get(key) is not None:
                    alpha_count += 1
        group = 1 if page.get("/Group") is not None else 0
        try:
            text_chars = len(page.extract_text() or "")
        except Exception:
            text_chars = 0
        image_page = image_count > 0
        image_dominant = bool(
            image_page and (
                iccbased_image_count > 0
                or (
                    non_image_xobjects == 0
                    and non_image_paint_ops == 0
                    and inline_image_markers == 0
                    and smask_count == 0
                    and alpha_count == 0
                    and group == 0
                    and len(shadings) == 0
                )
            )
        )
        vector_text_smask_dominant = bool(
            image_page and not image_dominant and (
                text_chars > 0
                or non_image_xobjects > 0
                or non_image_paint_ops > 0
                or inline_image_markers > 0
                or smask_count > 0
                or alpha_count > 0
                or group > 0
                or len(shadings) > 0
            )
        )
        unresolved_image_content = bool(
            not image_page and (non_image_xobjects > 0 or inline_image_markers > 0)
        )
        ambiguous_image = bool(
            unresolved_image_content
            or (image_page and not image_dominant and not vector_text_smask_dominant)
        )
        if iccbased_image_count > 0:
            page_class = "ICCBased_IMAGE"
        elif image_dominant:
            page_class = "IMAGE_DOMINANT"
        elif vector_text_smask_dominant:
            page_class = "VECTOR_TEXT_SMask"
        elif ambiguous_image:
            page_class = "AMBIGUOUS_IMAGE"
        else:
            page_class = "VECTOR_TEXT"
        row = {
            "page": index,
            "media_box_pt": [float(page.mediabox.width), float(page.mediabox.height)],
            "text_chars": text_chars,
            "xobjects": len(xobjects) if hasattr(xobjects, "__len__") else 0,
            "image_xobjects": image_count,
            "iccbased_image_xobjects": iccbased_image_count,
            "image_xobject_fraction": image_count / max(len(xobjects), 1),
            "image_details": image_details,
            "non_image_xobjects": non_image_xobjects,
            "non_image_paint_ops": non_image_paint_ops,
            "inline_image_markers": inline_image_markers,
            "extgstates": len(extgstates) if hasattr(extgstates, "__len__") else 0,
            "smask_entries": smask_count,
            "alpha_entries": alpha_count,
            "group": bool(group),
            "shadings": len(shadings) if hasattr(shadings, "__len__") else 0,
            "page_class": page_class,
            "image_dominant": image_dominant,
            "vector_text_smask_dominant": vector_text_smask_dominant,
            "ambiguous_image": ambiguous_image,
            "unresolved_image_content": unresolved_image_content,
        }
        pages.append(row)
        totals["image_xobjects"] += image_count
        totals["xobjects"] += row["xobjects"]
        totals["extgstates"] += row["extgstates"]
        totals["smask_entries"] += smask_count
        totals["alpha_entries"] += alpha_count
        totals["groups"] += group
        totals["shadings"] += row["shadings"]
        totals["iccbased_image_xobjects"] += iccbased_image_count
        totals["image_xobject_pages"] += int(image_page)
        totals["image_dominant_pages"] += int(image_dominant)
        totals["ambiguous_image_pages"] += int(ambiguous_image)
    return {
        "page_count": len(reader.pages),
        "producer": str((reader.metadata or {}).get("/Producer", "")),
        "creator": str((reader.metadata or {}).get("/Creator", "")),
        "pages": pages,
        "totals": totals,
        "has_smask": totals["smask_entries"] > 0,
        "has_transparency_group": totals["groups"] > 0,
        "has_image": totals["image_xobjects"] > 0,
    }


def classify_pdf(features: dict[str, Any]) -> dict[str, Any]:
    pages = features["pages"]
    page_classes = [str(page.get("page_class", "UNKNOWN")) for page in pages]
    icc_pages = [page["page"] for page in pages if page.get("iccbased_image_xobjects", 0) > 0]
    dominant_pages = [page["page"] for page in pages if page.get("image_dominant")]
    ambiguous_pages = [page["page"] for page in pages if page.get("ambiguous_image")]
    wps_quartz_regenerated = (
        str(features.get("creator", "")).startswith("WPS Office")
        and "Quartz PDFContext" in str(features.get("producer", ""))
    )
    if icc_pages:
        if wps_quartz_regenerated:
            return {
                "pdf_class": "ICCBased_IMAGE_HEAVY",
                "route": "GENERIC_HIGHLIGHT_A",
                "page_classes": page_classes,
                "native_pages": [],
                "ambiguous_pages": ambiguous_pages,
                "wps_quartz_regenerated": True,
                "why": (
                    "ICCBased image XObject with WPS Office creator and "
                    "Quartz PDFContext producer; use highlight A"
                ),
            }
        return {
            "pdf_class": "ICCBased_IMAGE_HEAVY",
            "route": "NATIVE",
            "page_classes": page_classes,
            "native_pages": icc_pages,
            "ambiguous_pages": ambiguous_pages,
            "wps_quartz_regenerated": False,
            "why": f"ICCBased image XObject present on page(s) {icc_pages}; preserve image tone with native path",
        }
    if ambiguous_pages:
        return {
            "pdf_class": "AMBIGUOUS_IMAGE",
            "route": "NATIVE",
            "page_classes": page_classes,
            "native_pages": dominant_pages,
            "ambiguous_pages": ambiguous_pages,
            "why": f"image placement/content is not safely classifiable on page(s) {ambiguous_pages}; fail closed to native",
        }
    if dominant_pages:
        return {
            "pdf_class": "IMAGE_HEAVY",
            "route": "NATIVE",
            "page_classes": page_classes,
            "native_pages": dominant_pages,
            "ambiguous_pages": [],
            "why": f"image-only page content is dominant on page(s) {dominant_pages}; use native path",
        }
    return {
        "pdf_class": "VECTOR_TEXT_SMask",
        "route": "GENERIC_HIGHLIGHT_A",
        "page_classes": page_classes,
        "native_pages": [],
        "ambiguous_pages": [],
        "why": "no ICCBased/image-dominant or ambiguous page; vector/text/SMask content is safe for highlight A",
    }


def _run(command: list[str], stdout: Path, stderr: Path, env: dict[str, str], timeout: float) -> None:
    with stdout.open("wb") as stdout_stream, stderr.open("wb") as stderr_stream:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=stdout_stream,
            stderr=stderr_stream, env=env, close_fds=True, start_new_session=True,
        )
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                raise RuntimeError(f"child timeout after {timeout:g}s")
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                process.wait()
    if code != 0:
        raise RuntimeError(f"child exited with status {code}")


def _read_pbm(path: Path) -> list[np.ndarray]:
    data = path.read_bytes()
    pages: list[np.ndarray] = []
    pos = 0
    while pos < len(data):
        if data[pos:pos + 2] != b"P4":
            raise RuntimeError(f"unexpected PBM page header at offset {pos}")
        pos += 2
        tokens: list[bytes] = []
        while len(tokens) < 2:
            while pos < len(data) and data[pos:pos + 1] in b" \t\r\n":
                pos += 1
            if pos < len(data) and data[pos:pos + 1] == b"#":
                newline = data.find(b"\n", pos)
                if newline < 0:
                    raise RuntimeError("unterminated PBM comment")
                pos = newline + 1
                continue
            end = pos
            while end < len(data) and data[end:end + 1] not in b" \t\r\n":
                end += 1
            if end == pos:
                raise RuntimeError("truncated PBM header")
            tokens.append(data[pos:end])
            pos = end
        width, height = map(int, tokens)
        if (width, height) != (FULL_W, FULL_H):
            raise RuntimeError(f"unexpected PBM geometry {(width, height)}")
        if pos >= len(data) or data[pos:pos + 1] not in b" \t\r\n":
            raise RuntimeError("missing PBM header separator")
        pos += 2 if data[pos:pos + 2] == b"\r\n" else 1
        row_bytes = (width + 7) // 8
        end = pos + row_bytes * height
        if end > len(data):
            raise RuntimeError("truncated PBM payload")
        raw = np.frombuffer(data[pos:end], dtype=np.uint8).reshape(height, row_bytes)
        pages.append(np.unpackbits(raw, axis=1, bitorder="big")[:, :width].astype(np.uint8))
        pos = end
    if not pages:
        raise RuntimeError("Ghostscript produced no PBM pages")
    return pages


def _read_raster(path: Path) -> tuple[list[bytes], bytes, str, list[dict[str, int]]]:
    data = path.read_bytes()
    if len(data) < 4 or data[:4] not in RASTER_MAGICS:
        raise RuntimeError("native renderer did not produce CUPS Raster")
    magic = data[:4]
    endian = "<" if magic in {b"tSaR", b"2SaR", b"3SaR"} else ">"
    headers: list[bytes] = []
    fields: list[dict[str, int]] = []
    pos = 0
    while pos < len(data):
        if pos == 0:
            header_len = HEADER_SIZES[magic]
            header = data[pos:pos + header_len]
        else:
            if data[pos:pos + 4] in RASTER_MAGICS:
                if data[pos:pos + 4] != magic:
                    raise RuntimeError("mixed CUPS Raster stream formats")
                pos += 4
            header_len = HEADER_SIZES[magic] - 4
            header = data[pos:pos + header_len]
        if len(header) != header_len:
            raise RuntimeError("truncated CUPS Raster page header")
        base = 4 if pos == 0 else 0
        u32 = lambda off: struct.unpack_from(endian + "I", header, base + off)[0]
        width, height = u32(372), u32(376)
        bpc, bpp, bpl = u32(384), u32(388), u32(392)
        if (width, height, bpc, bpp, bpl) != (CONTENT_W, CONTENT_H, 1, 1, 594):
            raise RuntimeError(f"native raster contract mismatch {(width, height, bpc, bpp, bpl)}")
        payload_start = pos + header_len
        payload_end = payload_start + height * bpl
        if payload_end > len(data):
            raise RuntimeError("truncated native Raster payload")
        headers.append(header)
        fields.append({"width": width, "height": height, "bits_per_color": bpc,
                       "bits_per_pixel": bpp, "bytes_per_line": bpl})
        pos = payload_end
    return headers, magic, endian, fields


def _pack_raster(headers: list[bytes], magic: bytes, endian: str,
                 pages: list[np.ndarray]) -> bytes:
    if len(headers) != len(pages):
        raise RuntimeError("page count changed while packing generic Raster")
    output = bytearray()
    for index, (header, page) in enumerate(zip(headers, pages)):
        if page.shape != (CONTENT_H, CONTENT_W):
            raise RuntimeError(f"generic page geometry mismatch: {page.shape}")
        h = bytearray(header)
        base = 4 if index == 0 else 0
        for offset, value in ((384, 1), (388, 1), (392, 594),
                              (396, 0), (400, 3), (404, 17), (420, 1)):
            struct.pack_into(endian + "I", h, base + offset, value)
        output.extend(h)
        output.extend(np.packbits(page, axis=1, bitorder="big").tobytes())
    return bytes(output)


def render_generic(source: Path, filter_args: list[str], output: Path,
                   native_renderer: Path, ghostscript: Path, ghostscript_lib: Path,
                   ppd: Path, timeout: float) -> dict[str, Any]:
    """Render one classified document to a complete CUPS Raster stream."""
    if len(filter_args) != 6 or filter_args[5] != str(source):
        raise RuntimeError("generic renderer requires a normalized PDF filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hp116w-generic-600-", dir=str(output.parent)) as root_name:
        root = Path(root_name)
        native = root / "native.raster"
        native_err = root / "native.stderr"
        native_env = os.environ.copy()
        native_env["PPD"] = str(ppd)
        _run([str(native_renderer), *filter_args], native, native_err, native_env, timeout)
        headers, magic, endian, native_fields = _read_raster(native)
        page_count = len(headers)
        pbm = root / "generic.pbm"
        gs_err = root / "ghostscript.stderr"
        gs_root = ghostscript_lib.resolve()
        gs_env = os.environ.copy()
        gs_env["GS_LIB"] = f"{gs_root / 'Resource'}:{gs_root}"
        gs_command = [
            str(ghostscript), "-q", "-dBATCH", "-dNOPAUSE",
            f"-I{gs_root / 'Resource' / 'Init'}", f"-I{gs_root / 'Resource'}", f"-I{gs_root}",
            "-sDEVICE=pbmraw", "-r600", "-g4961x7016", "-dFIXEDMEDIA",
            "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4", "-dFirstPage=1",
            f"-dLastPage={page_count}", f"-sOutputFile={pbm}",
            "-c", HALFTONE_SETUP, HIGHLIGHT_A_TRANSFER, "-f", str(source),
        ]
        _run(gs_command, pbm, gs_err, gs_env, timeout)
        full_pages = _read_pbm(pbm)
        if len(full_pages) != page_count:
            raise RuntimeError(f"generic page count mismatch {len(full_pages)} != {page_count}")
        cropped = [page[IMAGEABLE_Y:IMAGEABLE_Y + CONTENT_H,
                         IMAGEABLE_X:IMAGEABLE_X + CONTENT_W] for page in full_pages]
        packed = _pack_raster(headers, magic, endian, cropped)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(packed)
        os.replace(temporary, output)
    return {
        "renderer": "Ghostscript direct highlight A",
        "page_count": page_count,
        "raster_format": {
            "magic": magic.decode("ascii"), "width": CONTENT_W, "height": CONTENT_H,
            "resolution": [600, 600], "color_space": "Gray", "bits_per_color": 1,
            "bits_per_pixel": 1, "bytes_per_line": 594, "compression": 17,
        },
        "native_header_pages": native_fields,
        "halftone": "CosineDot",
        "screen_lpi": 106.17,
        "screen_angle_degrees": 45.0,
        "transfer": "highlight A",
    }


def main() -> int:
    """Small diagnostic CLI; production normally imports this module."""
    if len(sys.argv) == 3 and sys.argv[1] == "classify":
        print(json.dumps(classify_pdf(pdf_features(Path(sys.argv[2]))), ensure_ascii=False))
        return 0
    print("usage: hp116w_generic_600.py classify PDF", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
