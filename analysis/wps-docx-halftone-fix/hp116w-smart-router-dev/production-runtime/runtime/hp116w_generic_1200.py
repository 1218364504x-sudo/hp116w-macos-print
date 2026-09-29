#!/usr/bin/python3
"""Production 1200 dpi RGB235-only Generic renderer.

The classifier is shared with the frozen 600 dpi adapter.  This module keeps
the 1200 profile independent: it applies RGB235 and the validated CosineDot
screen, without the 600 dpi Highlight A transfer.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RUNTIME_ROOT = Path(__file__).resolve().parent
_PINNED_SITE_PACKAGES = Path("/Library/Application Support/HP116W/runtime/site-packages")
_LOCAL_SITE_PACKAGES = RUNTIME_ROOT / "site-packages"
SITE_PACKAGES = (_PINNED_SITE_PACKAGES if _PINNED_SITE_PACKAGES.is_dir()
                 else _LOCAL_SITE_PACKAGES)
if SITE_PACKAGES.is_dir() and str(SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SITE_PACKAGES))

import numpy as np
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject


DPI = 1200
CONTENT_W, CONTENT_H = 9500, 13617
IMAGEABLE = 12.5
IMAGEABLE_X = IMAGEABLE_Y = round(IMAGEABLE * DPI / 72)
HEADER_SIZES = {b"RaSt": 420, b"tSaR": 420,
                b"RaS2": 1800, b"2SaR": 1800,
                b"RaS3": 1800, b"3SaR": 1800}
RASTER_MAGICS = set(HEADER_SIZES)
GRAY_TOKEN = b"0.9098039 0.9098039 0.9098039 sc"
HALFTONE_SETUP = (
    "<< /HalftoneType 1 /Frequency 106.17 /Angle 45 "
    "/SpotFunction {180 mul cos exch 180 mul cos add 2 div} >> "
    "/Default exch /Halftone defineresource sethalftone"
)


def _load_600_adapter():
    path = RUNTIME_ROOT / "hp116w_generic_600.py"
    spec = importlib.util.spec_from_file_location("hp116w_generic_600_shared", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared classifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SHARED = _load_600_adapter()
pdf_features = _SHARED.pdf_features


def classify_pdf(features: dict[str, Any]) -> dict[str, Any]:
    result = dict(_SHARED.classify_pdf(features))
    if result.get("route") == "GENERIC_HIGHLIGHT_A":
        result["route"] = "GENERIC_RGB235_1200"
        result["why"] = (
            str(result.get("why", ""))
            + "; use 1200 RGB235-only Generic (no Highlight A transfer)"
        ).strip("; ")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], stdout: Path, stderr: Path,
         env: dict[str, str], timeout: float) -> None:
    with stdout.open("wb") as stdout_stream, stderr.open("wb") as stderr_stream:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
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
            raise RuntimeError(f"child timeout after {timeout:g}s") from exc
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if code != 0:
            raise RuntimeError(f"child exited with status {code}")


def _has_1200_option(options: str) -> bool:
    for raw in re.split(r"[\s,]+", options.strip()):
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        key = name.lower()
        token = value.strip().strip('"').lower()
        if key not in {"quality", "resolution", "cupsprintquality"}:
            continue
        if key == "cupsprintquality" and token in {"high", "best"}:
            return True
        if token in {"1200", "1200dpi", "1200x1200"}:
            return True
    return False


def _force_1200_filter_args(filter_args: list[str], ppd: Path) -> list[str]:
    if len(filter_args) != 6:
        raise RuntimeError("generic renderer requires six CUPS filter arguments")
    args = list(filter_args)
    options = args[4] or ""
    if _has_1200_option(options):
        return args
    ppd_text = ppd.read_text(errors="ignore")
    if re.search(r"(?m)^\*Quality\s+1200dpi(?:/|\s)", ppd_text):
        quality_option = "Quality=1200dpi"
    elif re.search(r"(?mi)^\*cupsPrintQuality", ppd_text):
        quality_option = "cupsPrintQuality=High"
    else:
        quality_option = "Resolution=1200dpi"
    args[4] = f"{options} {quality_option}".strip()
    return args


def _normalize(source: Path, destination: Path, report: Path,
               timeout: float) -> None:
    command = [
        sys.executable,
        str(RUNTIME_ROOT / "hp116w_normalize.py"),
        str(source),
        str(destination),
        "--target", "595", "842",
        "--margins", "12.5", "12.5", "582.5", "829.5",
        "--report", str(report),
    ]
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    if SITE_PACKAGES.is_dir():
        environment["PYTHONPATH"] = str(SITE_PACKAGES)
    else:
        environment.pop("PYTHONPATH", None)
    _run(command, destination.with_suffix(".stdout"),
         destination.with_suffix(".stderr"), environment, timeout)


def _rgb235_pdf(source: Path, destination: Path) -> None:
    reader = PdfReader(str(source), strict=False)
    writer = PdfWriter()
    value = 235 / 255.0
    replacement = (f"{value:.9f} {value:.9f} {value:.9f} sc").encode("ascii")
    for page in reader.pages:
        contents = page.get_contents()
        data = contents.get_data() if contents is not None else b""
        stream = DecodedStreamObject()
        stream.set_data(data.replace(GRAY_TOKEN, replacement))
        page[NameObject("/Contents")] = stream
        writer.add_page(page)
    if reader.metadata:
        writer.add_metadata({str(k): str(v) for k, v in reader.metadata.items() if v is not None})
    with destination.open("wb") as stream:
        writer.write(stream)


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
        row_bytes = (width + 7) // 8
        if width < IMAGEABLE_X + CONTENT_W or height < IMAGEABLE_Y + CONTENT_H:
            raise RuntimeError(f"PBM geometry too small: {width}x{height}")
        if pos >= len(data) or data[pos:pos + 1] not in b" \t\r\n":
            raise RuntimeError("missing PBM header separator")
        pos += 2 if data[pos:pos + 2] == b"\r\n" else 1
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
        first = pos == 0
        if first:
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
        base = 4 if first else 0
        u32 = lambda off: struct.unpack_from(endian + "I", header, base + off)[0]
        width, height = u32(372), u32(376)
        bpc, bpp, bpl = u32(384), u32(388), u32(392)
        compression = u32(404)
        if (width, height, bpc, bpp, bpl, compression) != (CONTENT_W, CONTENT_H, 1, 1, 1188, 17):
            raise RuntimeError(
                f"native raster contract mismatch {(width, height, bpc, bpp, bpl, compression)}"
            )
        payload_start = pos + header_len
        payload_end = payload_start + height * bpl
        if payload_end > len(data):
            raise RuntimeError("truncated native Raster payload")
        headers.append(header)
        fields.append({
            "width": width, "height": height, "bits_per_color": bpc,
            "bits_per_pixel": bpp, "bytes_per_line": bpl,
            "compression": compression,
        })
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
        for offset, value in ((384, 1), (388, 1), (392, 1188),
                              (396, 0), (400, 3), (404, 17), (420, 1)):
            struct.pack_into(endian + "I", h, base + offset, value)
        output.extend(h)
        output.extend(np.packbits(page, axis=1, bitorder="big").tobytes())
    return bytes(output)


def render_generic(source: Path, filter_args: list[str], output: Path,
                   native_renderer: Path, ghostscript: Path, ghostscript_lib: Path,
                   ppd: Path, timeout: float) -> dict[str, Any]:
    """Render one classified document to a complete 1200 dpi CUPS Raster stream."""
    if len(filter_args) != 6 or filter_args[5] != str(source):
        raise RuntimeError("generic renderer requires a normalized PDF filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hp116w-generic-1200-", dir=str(output.parent)) as root_name:
        root = Path(root_name)
        native = root / "native.raster"
        native_err = root / "native.stderr"
        native_env = os.environ.copy()
        native_env["PPD"] = str(ppd)
        native_filter_args = _force_1200_filter_args(filter_args, ppd)
        _run([str(native_renderer), *native_filter_args], native, native_err, native_env, timeout)
        headers, magic, endian, native_fields = _read_raster(native)
        page_count = len(headers)

        normalized = root / "normalized.pdf"
        _normalize(source, normalized, root / "normalize.json", timeout)
        toned = root / "rgb235.pdf"
        _rgb235_pdf(normalized, toned)
        pbm = root / "generic.pbm"
        gs_root = ghostscript_lib.resolve()
        gs_env = os.environ.copy()
        gs_env["GS_LIB"] = f"{gs_root / 'Resource'}:{gs_root}"
        gs_command = [
            str(ghostscript), "-q", "-dBATCH", "-dNOPAUSE",
            f"-I{gs_root / 'Resource' / 'Init'}", f"-I{gs_root / 'Resource'}", f"-I{gs_root}",
            "-sDEVICE=pbmraw", "-r1200", "-dTextAlphaBits=1", "-dGraphicsAlphaBits=1",
            "-dFirstPage=1", f"-dLastPage={page_count}", f"-sOutputFile={pbm}",
            "-c", HALFTONE_SETUP, "-f", str(toned),
        ]
        _run(gs_command, pbm, root / "ghostscript.stderr", gs_env, timeout)
        full_pages = _read_pbm(pbm)
        if len(full_pages) != page_count:
            raise RuntimeError(f"generic page count mismatch {len(full_pages)} != {page_count}")
        cropped = [
            page[IMAGEABLE_Y:IMAGEABLE_Y + CONTENT_H,
                 IMAGEABLE_X:IMAGEABLE_X + CONTENT_W]
            for page in full_pages
        ]
        packed = _pack_raster(headers, magic, endian, cropped)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(packed)
        os.replace(temporary, output)
    return {
        "renderer": "Ghostscript direct RGB235-only Generic",
        "page_count": page_count,
        "raster_format": {
            "magic": magic.decode("ascii"), "width": CONTENT_W, "height": CONTENT_H,
            "resolution": [1200, 1200], "color_space": "Gray",
            "bits_per_color": 1, "bits_per_pixel": 1, "bytes_per_line": 1188,
            "compression": 17,
        },
        "native_header_pages": native_fields,
        "native_filter_options": native_filter_args[4],
        "input_tone_rgb": 235,
        "halftone": "CosineDot",
        "screen_lpi": 106.17,
        "screen_angle_degrees": 45.0,
        "transfer": "none",
        "output_sha256": _sha256(output),
    }


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "classify":
        print(json.dumps(classify_pdf(pdf_features(Path(sys.argv[2]))), ensure_ascii=False))
        return 0
    print("usage: hp116w_generic_1200.py classify PDF", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
