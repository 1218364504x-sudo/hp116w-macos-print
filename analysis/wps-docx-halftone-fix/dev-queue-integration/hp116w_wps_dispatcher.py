#!/usr/bin/python3
"""CUPS-callable, fail-closed WPS/DOCX selective Spot106 dispatcher.

This filter accepts a PDF as the
standard CUPS filter's last argument and writes a CUPS Raster v3 1-bit K page
to stdout.  It invokes the production ``cgpdftoraster`` indirectly through
``cupsfilter -p`` as a read-only rasterizer, then changes only neutral vector
gray-fill objects when the combined WPS detector is HIGH and the request is
600 dpi.  Ambiguous/unsupported input is passed through unchanged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

# CUPS starts filters with a sanitized HOME/PATH and does not expose the
# interactive user's site-packages.  Load only the pinned runtime from a
# fixed absolute root; the environment override is reserved for offline tests.
RUNTIME_ROOT = Path(os.environ.get(
    "HP116W_RUNTIME_ROOT",
    "/Library/Application Support/HP116W/runtime",
))
SITE_PACKAGES = RUNTIME_ROOT / "site-packages"
os.environ["PYTHONNOUSERSITE"] = "1"
os.environ["PYTHONPATH"] = str(SITE_PACKAGES)
sys.path = [p for p in sys.path if not p.startswith("/Users/")]
sys.path.insert(0, str(SITE_PACKAGES))

import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, NameObject

PROD_PPD = Path("/private/etc/cups/ppd/HP116W_High_Quality.ppd")
# The administrator install places this executable in a CUPS
# allow-listed filter directory.  Its dependent libraries are bundled under
# /Library/Printers/HP116W and the install script rewrites their load
# commands to that absolute, read-only path.  The environment override is
# used only by offline tests.
GS = Path(os.environ.get("HP116W_GS", "/usr/libexec/cups/filter/hp116w_gs"))
GS_LIB = os.environ.get(
    "HP116W_GS_LIB",
    "/usr/libexec/cups/filter/hp116w_gs_resources/share/ghostscript",
)
NORMALIZER = RUNTIME_ROOT / "hp116w_normalize.py"
CUPSFILTER = Path("/usr/sbin/cupsfilter")
FROZEN_RASTERTOQPDL = Path("/usr/libexec/cups/filter/rastertoqpdl")
RUNTIME_CONFIG = RUNTIME_ROOT / "config.json"
W, H, BPL, HEADER = 4750, 6808, 594, 1800
W1200, H1200, BPL1200 = 9500, 13617, 1188
IMAGEABLE = 12.5
GRAY_TOKEN = b"0.9098039 0.9098039 0.9098039 sc"
NUM = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
PAGE_RANGES = re.compile(r"(?:^|\s)page-ranges=(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))")
SUPPORTED_MEDIA_POINTS = ((612.0, 792.0), (595.0, 842.0))
MEDIA_TOLERANCE_PT = 1.0


TRACE_JOB_ID = "-"
TRACE_FILE: Path | None = None


def trace(event: str, status: object = "ok", **fields: object) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    record = {"timestamp": stamp, "job_id": TRACE_JOB_ID, "stage": event,
              "pid": os.getpid(), "status": status, **fields}
    details = " ".join(f"{key}={value}" for key, value in record.items())
    line = f"HP116W_TRACE {details}"
    print(line, file=sys.stderr, flush=True)
    if TRACE_FILE is not None:
        try:
            with TRACE_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass


class PageRangeSafetyAbort(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def supported_media(width: float, height: float) -> bool:
    return any(
        abs(width - media_width) <= MEDIA_TOLERANCE_PT
        and abs(height - media_height) <= MEDIA_TOLERANCE_PT
        for media_width, media_height in SUPPORTED_MEDIA_POINTS
    )


def gs_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GS_LIB"] = f"{GS_LIB}/Resource:{GS_LIB}"
    env.setdefault("TMPDIR", "/private/var/spool/cups/tmp")
    return env


def gs_command(extra: list[str]) -> list[str]:
    """Build every Ghostscript invocation from the installed runtime."""
    resource_root = Path(GS_LIB)
    return [
        str(GS), "-q", "-dBATCH", "-dNOPAUSE",
        f"-I{resource_root / 'Resource' / 'Init'}",
        f"-I{resource_root / 'Resource'}",
        f"-I{resource_root}",
        *extra,
    ]


def run_gs(extra: list[str], **kwargs):
    """Run the fixed Ghostscript binary with deterministic resources."""
    kwargs.setdefault("env", gs_env())
    # Never permit a caller to weaken descriptor isolation for a CUPS child.
    kwargs["close_fds"] = True
    # Ghostscript output is always redirected to the requested file (or is
    # irrelevant for this helper).  Never let an unexpected stdout write
    # contaminate the CUPS payload stream.
    kwargs.setdefault("stdout", subprocess.DEVNULL)
    trace("GS_START", argv=" ".join(gs_command(extra)))
    started = dt.datetime.now(dt.timezone.utc)
    with tempfile.TemporaryFile() as error_stream:
        kwargs["stderr"] = error_stream
        proc = subprocess.Popen(gs_command(extra), **kwargs)
        trace("GS_PID", pid_child=proc.pid)
        result = proc.wait()
        error_stream.seek(0)
        stderr_bytes = len(error_stream.read())
    trace("GS_EXIT_CODE", status=result, exit_code=result)
    trace("GS_EXIT", status=result, exit_code=result,
          stderr_bytes=stderr_bytes,
          elapsed_ms=int((dt.datetime.now(dt.timezone.utc)-started).total_seconds()*1000))
    if result != 0:
        raise subprocess.CalledProcessError(result, gs_command(extra))
    return result


def active_ppd() -> Path:
    """Use the queue-provided PPD, with production as a safe standalone default."""
    return Path(os.environ.get("PPD", str(PROD_PPD)))


def runtime_config() -> dict:
    if not RUNTIME_CONFIG.is_file():
        raise RuntimeError(f"runtime config missing: {RUNTIME_CONFIG}")
    return json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))


def parse_page_ranges(options: str, page_count: int) -> tuple[list[int], str | None]:
    """Return zero-based source pages selected by standard CUPS page-ranges."""
    match = PAGE_RANGES.search(options)
    if not match:
        return list(range(page_count)), None
    spec = next(value for value in match.groups() if value is not None)
    selected: list[int] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            raise ValueError(f"invalid page-ranges: {spec}")
        if "-" in item:
            first_text, last_text = item.split("-", 1)
            first = int(first_text) if first_text else 1
            last = int(last_text) if last_text else page_count
        else:
            first = last = int(item)
        if first < 1 or last < first or last > page_count:
            raise ValueError(f"page-ranges outside 1..{page_count}: {spec}")
        for page_number in range(first, last + 1):
            index = page_number - 1
            if index not in selected:
                selected.append(index)
    if not selected:
        raise ValueError(f"empty page-ranges: {spec}")
    return selected, spec


def write_page_pdf(reader: PdfReader, index: int, out: Path) -> None:
    writer = PdfWriter()
    if reader.metadata:
        writer.add_metadata({str(k): str(v) for k, v in reader.metadata.items() if v is not None})
    writer.add_page(reader.pages[index])
    with out.open("wb") as stream:
        writer.write(stream)


def classify(pdf: Path) -> dict:
    try:
        reader = PdfReader(str(pdf))
        page = reader.pages[0]
        meta = reader.metadata or {}
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        contents = page.get_contents()
        data = contents.get_data() if contents is not None else b""
        resources = page.get("/Resources", {})
        cs_obj = resources.get("/ColorSpace", {})
        try:
            cs_obj = cs_obj.get_object()
        except AttributeError:
            pass
        colorspace = str(cs_obj)
        if isinstance(cs_obj, dict):
            colorspace = " ".join(str(v.get_object() if hasattr(v, "get_object") else v) for v in cs_obj.values())
        xobjects = resources.get("/XObject", {})
        try:
            xobjects = xobjects.get_object()
        except AttributeError:
            pass
        sig = {
            "creator_wps": str(meta.get("/Creator", "")).startswith("WPS Office"),
            "title_docx": str(meta.get("/Title", "")).lower().endswith(".docx"),
            "producer_quartz": "Quartz PDFContext" in str(meta.get("/Producer", "")),
            # Keep the historical field name for report compatibility;
            # it now means one of the supported portrait media sizes.
            "letter_media": supported_media(w, h),
            "iccbased_rgb": "/ICCBased" in colorspace,
            "vector_only": len(xobjects) == 0,
            "neutral_gray_signal": GRAY_TOKEN in data,
            "content_bytes": len(data),
        }
        score = sum(bool(v) for k, v in sig.items() if k not in {"content_bytes"})
        identity_high = all(sig[k] for k in ("creator_wps", "title_docx", "producer_quartz", "letter_media", "iccbased_rgb", "vector_only"))
        high = identity_high
        return {"decision": "HIGH" if high else "BYPASS", "confidence": 0.98 if high else 0.0, "signals": sig, "score": score, "target_gray_eligible": bool(high and sig["neutral_gray_signal"])}
    except Exception as exc:
        return {"decision": "BYPASS", "confidence": 0.0, "error": repr(exc)}


def normalize(pdf: Path, out: Path, report: Path) -> dict:
    cmd = [sys.executable, str(NORMALIZER), str(pdf), str(out), "--target", "595", "842", "--margins", "12.5", "12.5", "582.5", "829.5", "--report", str(report)]
    trace("NORMALIZE_START", argv=" ".join(cmd))
    started = dt.datetime.now(dt.timezone.utc)
    with tempfile.TemporaryFile() as error_stream:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=error_stream,
                                env=os.environ.copy(), close_fds=True)
        trace("NORMALIZE_PID", pid_child=proc.pid)
        rc = proc.wait()
        error_stream.seek(0); stderr_bytes = len(error_stream.read())
    trace("NORMALIZE_DONE", status=rc, exit_code=rc, stderr_bytes=stderr_bytes,
          elapsed_ms=int((dt.datetime.now(dt.timezone.utc)-started).total_seconds()*1000))
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return json.loads(report.read_text())


def requested_resolution(options: str = "") -> int:
    """Resolve the queue default while honoring an explicit CUPS quality."""
    explicit: list[int] = []
    for raw in re.split(r"[\s,]+", options.strip()):
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        if name.lower() not in {"resolution", "quality", "cupsprintquality"}:
            continue
        token = value.strip().strip('"').lower()
        if token in {"high", "best"}:
            explicit.append(1200)
        elif token in {"normal", "standard"}:
            explicit.append(600)
        else:
            match = re.fullmatch(r"([0-9]+)(?:x[0-9]+)?(?:dpi)?", token)
            if match:
                explicit.append(int(match.group(1)))
    if explicit:
        if len(set(explicit)) != 1:
            raise RuntimeError(f"conflicting resolution options: {explicit}")
        return explicit[0]
    return 1200 if os.environ.get("PRINTER", "").strip() == "HP116W_1200dpi" else 600


def rasterize(pdf: Path, out: Path, log: Path, options: str = "") -> None:
    # The queue's public contract is the standard CUPS Resolution
    # option.  Keep a conservative 600 dpi default when a caller omits it.
    resolution = f"{requested_resolution(options)}dpi"
    ppd_text = active_ppd().read_text(errors="ignore")
    if "cupsPrintQuality" in ppd_text:
        quality_option = "cupsPrintQuality=High" if resolution == "1200dpi" else "cupsPrintQuality=Normal"
    elif re.search(r"(?m)^\*Quality\s+1200dpi(?:/|\s)", ppd_text):
        quality_option = f"Quality={resolution}"
    else:
        quality_option = f"Resolution={resolution}"
    cmd = [str(CUPSFILTER), "-p", str(active_ppd()), "-m", "application/vnd.cups-raster", "-o", "ColorModel=Gray", "-o", "PageSize=A4", "-o", quality_option, "-o", "Duplex=None", str(pdf)]
    trace("RASTERIZE_START", argv=" ".join(cmd))
    started = dt.datetime.now(dt.timezone.utc)
    with out.open("wb") as fo, log.open("wb") as fe:
        proc = subprocess.Popen(cmd, stdout=fo, stderr=fe, close_fds=True)
        trace("RASTERIZE_PID", pid_child=proc.pid)
        rc = proc.wait()
    trace("RASTERIZE_DONE", status=rc, exit_code=rc,
          output_bytes=out.stat().st_size if out.exists() else 0,
          elapsed_ms=int((dt.datetime.now(dt.timezone.utc)-started).total_seconds()*1000))
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def read_raster(path: Path, resolution: int = 600) -> tuple[bytes, np.ndarray]:
    raw = path.read_bytes()
    if resolution == 1200:
        width, height, bytes_per_line = W1200, H1200, BPL1200
    elif resolution == 600:
        width, height, bytes_per_line = W, H, BPL
    else:
        raise RuntimeError(f"unsupported resolution: {resolution}")
    if len(raw) != HEADER + height * bytes_per_line:
        raise RuntimeError("unexpected CUPS raster size")
    header_width = int.from_bytes(raw[376:380], "little")
    header_height = int.from_bytes(raw[380:384], "little")
    bpl = int.from_bytes(raw[396:400], "little")
    if (header_width, header_height, bpl) != (width, height, bytes_per_line):
        raise RuntimeError("unsupported geometry")
    bits = np.unpackbits(np.frombuffer(raw[HEADER:], np.uint8).reshape(height, bytes_per_line), axis=1, bitorder="big")[:, :width]
    return raw[:HEADER], bits.astype(np.uint8)


def write_raster(header: bytes, bits: np.ndarray, resolution: int = 600) -> bytes:
    if resolution == 1200:
        bytes_per_line = BPL1200
    elif resolution == 600:
        bytes_per_line = BPL
    else:
        raise RuntimeError(f"unsupported resolution: {resolution}")
    out = bytearray(header)
    for off, val in ((384, 1), (388, 1), (392, bytes_per_line), (400, 3), (404, 17), (420, 1)):
        struct.pack_into("<I", out, 4 + off, val)
    return bytes(out) + np.packbits(bits, axis=1, bitorder="big").tobytes()


def extract_gray_regions(pdf: Path) -> list[tuple[float, float, float, float]]:
    data = PdfReader(str(pdf)).pages[0].get_contents().get_data()
    rects = []
    pos = 0
    while True:
        idx = data.find(GRAY_TOKEN, pos)
        if idx < 0: break
        end = data.find(b" f", idx)
        if end < 0 or end - idx > 6000: break
        segment = data[idx + len(GRAY_TOKEN):end]
        toks = re.split(rb"\s+", segment)
        pending=[]; pts=[]
        for tok in toks:
            if NUM.fullmatch(tok): pending.append(float(tok)); continue
            if tok in (b"m", b"l") and len(pending) >= 2:
                pts.append((pending[-2], pending[-1])); pending=[]
            elif tok == b"re" and len(pending) >= 4:
                x,y,w,h = pending[-4:]; pts.extend([(x,y),(x+w,y),(x,y+h),(x+w,y+h)]); pending=[]
            elif tok in (b"c", b"v", b"y"):
                pending=[]
            elif tok == b"h":
                pending=[]
        if len(pts) >= 3:
            xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
            x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
            if (x1-x0)*(y1-y0) >= 100.0:
                rects.append((x0,y0,x1,y1))
        pos = idx + len(GRAY_TOKEN)
    return rects


def region_mask(gray_png: Path, rects: list[tuple[float, float, float, float]], resolution: int = 600) -> tuple[np.ndarray, int]:
    gray = np.asarray(Image.open(gray_png).convert("L"), dtype=np.uint8)
    if resolution == 1200:
        width, height = W1200, H1200
    elif resolution == 600:
        width, height = W, H
    else:
        raise RuntimeError(f"unsupported resolution: {resolution}")
    off = round(IMAGEABLE * resolution / 72)
    gray = gray[off:off+height, off:off+width]
    mask = np.zeros((height, width), dtype=bool)
    for x0,y0,x1,y1 in rects:
        a = round((x0-IMAGEABLE)*resolution/72); b = round((842-IMAGEABLE-y1)*resolution/72)
        c = round((x1-IMAGEABLE)*resolution/72); d = round((842-IMAGEABLE-y0)*resolution/72)
        if c>a and d>b: mask[max(0,b):min(height,d), max(0,a):min(width,c)] = True
    allowed = mask & (gray >= 228)
    return allowed, len(rects)


def spot_bits(pdf: Path, out: Path, resolution: int = 600) -> np.ndarray:
    setup = b"<< /HalftoneType 1 /Frequency 106 /Angle 45 /SpotFunction {180 mul cos exch 180 mul cos add 2 div} >> /Default exch /Halftone defineresource sethalftone"
    # Pass the complete resource search path explicitly.  Under the strict
    # macOS CUPS sandbox an inherited GS_LIB can be sanitized or resolved
    # relative to the filter process; explicit -I entries make gs_init.ps
    # lookup deterministic without touching production Ghostscript.
    run_gs([
        "-sDEVICE=pbmraw", f"-r{resolution}", "-dTextAlphaBits=1",
        "-dGraphicsAlphaBits=1", f"-sOutputFile={out}", "-c",
        setup.decode(), "-f", str(pdf),
    ])
    full = 1 - np.asarray(Image.open(out).convert("1"), dtype=np.uint8)
    if resolution == 1200:
        width, height = W1200, H1200
    elif resolution == 600:
        width, height = W, H
    else:
        raise RuntimeError(f"unsupported resolution: {resolution}")
    off = round(IMAGEABLE*resolution/72)
    return full[off:off+height, off:off+width]


def gray_tone_pdf(pdf: Path, out: Path, rgb: int) -> None:
    reader=PdfReader(str(pdf)); writer=PdfWriter(); value = rgb / 255.0
    repl=(f"{value:.9f} {value:.9f} {value:.9f} sc").encode("ascii")
    for page in reader.pages:
        data=page.get_contents().get_data(); stream=DecodedStreamObject(); stream.set_data(data.replace(GRAY_TOKEN,repl)); page[NameObject("/Contents")]=stream; writer.add_page(page)
    with out.open("wb") as f: writer.write(f)


def gray190_pdf(pdf: Path, out: Path) -> None:
    gray_tone_pdf(pdf, out, 190)


def dispatch_page(input_pdf: Path, options: str = "") -> tuple[bytes, dict]:
    with tempfile.TemporaryDirectory(prefix="hp116w-wps-") as td:
        t=Path(td); trace("WPS_DETECT_START", input_file=str(input_pdf)); cls=classify(input_pdf); trace("WPS_DETECT_DONE", decision=cls.get("decision")); control_pdf=input_pdf; norm_report=t/"normalize.json"
        resolution = requested_resolution(options)
        if cls["decision"] != "HIGH":
            out=t/"control.raster"; rasterize(control_pdf,out,t/"control.log",options)
            if resolution == 1200:
                return out.read_bytes(), {"classification":cls,"geometry":"BYPASS","mask_object_count":0,"spot106_invoked":False,"protected_xor":0}
            header,bits=read_raster(out,resolution); return write_raster(header,bits,resolution), {"classification":cls,"geometry":"BYPASS","mask_object_count":0,"spot106_invoked":False,"protected_xor":0}
        source_rects = extract_gray_regions(input_pdf) if cls.get("target_gray_eligible") else []
        norm=t/"normalized.pdf"; nreport=normalize(input_pdf,norm,norm_report)
        if any(p.get("mode") not in ("NORMALIZED","BYPASS") for p in nreport.get("pages",[])):
            out=t/"fallback.raster"; rasterize(input_pdf,out,t/"fallback.log",options)
            if resolution == 1200:
                return out.read_bytes(), {"classification":cls,"geometry":"FALLBACK_REQUIRED_1200","mask_object_count":0,"spot106_invoked":False,"protected_xor":0}
            header,bits=read_raster(out,resolution); return write_raster(header,bits,resolution), {"classification":cls,"geometry":"FALLBACK_REQUIRED","mask_object_count":0,"spot106_invoked":False,"protected_xor":0}
        control_r=t/"control.raster"; rasterize(norm,control_r,t/"control.log",options); header,control=read_raster(control_r,resolution)
        tone = 235 if resolution == 1200 else 190
        tone_source=t/(f"gray{tone}-source.pdf"); gray_tone_pdf(input_pdf,tone_source,tone)
        toned=t/(f"gray{tone}.pdf"); gray_report=t/"gray-normalize.json"; normalize(tone_source,toned,gray_report); spot=spot_bits(toned,t/"spot.pbm",resolution)
        gray_png=t/"gray.png"
        run_gs([
            "-sDEVICE=pnggray", f"-r{resolution}", f"-sOutputFile={gray_png}",
            str(norm),
        ])
        # Transform the source-object rectangles by the normalizer's dynamic
        # scale-1 matrix; do not use a Day01 constant.
        transformed=[]
        page_report=(nreport.get("pages") or [{}])[0]
        matrix=page_report.get("matrix", [1,0,0,1,0,0])
        tx,ty=float(matrix[4]),float(matrix[5])
        for x0,y0,x1,y1 in source_rects:
            transformed.append((x0+tx,y0+ty,x1+tx,y1+ty))
        allowed,count=region_mask(gray_png,transformed,resolution)
        if count == 0 or int(allowed.sum()) == 0:
            return write_raster(header,control,resolution), {"classification":cls,"route":f"WPS_SELECTIVE_{resolution}","geometry":nreport,"mask_object_count":count,"mask_area":int(allowed.sum()),"spot106_invoked":False,"protected_xor":0}
        candidate=control.copy(); candidate[allowed]=spot[allowed]; protected_xor=int(np.count_nonzero((candidate^control)[~allowed]))
        final=write_raster(header,candidate,resolution)
        return final, {"classification":cls,"route":f"WPS_SELECTIVE_{resolution}","geometry":nreport,"mask_object_count":count,"mask_area":int(allowed.sum()),"spot106_invoked":True,"input_tone_rgb":float(tone),"rgb235_active":resolution == 1200,"screen_lpi":106.17,"screen_angle":45.0,"protected_xor":protected_xor,"final_raster_sha256":sha(final)}


def dispatch(input_pdf: Path, options: str = "") -> tuple[bytes, dict]:
    """Apply page-ranges before per-page dispatch and enforce acceptance guard."""
    reader = PdfReader(str(input_pdf))
    input_page_count = len(reader.pages)
    selected, requested = parse_page_ranges(options, input_page_count)
    outputs: list[bytes] = []
    page_records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="hp116w-wps-pages-") as td:
        work = Path(td)
        for index in selected:
            # Preserve the exact one-page input used for the physical reference.
            if input_page_count == 1 and index == 0:
                page_pdf = input_pdf
            else:
                page_pdf = work / f"source-page-{index + 1}.pdf"
                write_page_pdf(reader, index, page_pdf)
            raster, record = dispatch_page(page_pdf, options)
            outputs.append(raster)
            record["source_page_number"] = index + 1
            page_records.append(record)

    output_page_count = len(outputs)
    config = runtime_config()
    acceptance_mode = os.environ.get("HP116W_ACCEPTANCE_MODE", str(config.get("acceptance_mode", False))).lower() in {"1", "true", "yes"}
    expected_pages = int(os.environ.get("HP116W_ACCEPTANCE_EXPECTED_PAGES", config.get("acceptance_expected_output_pages", 1)))
    guard = {
        "mode": acceptance_mode,
        "expected_output_pages": expected_pages if acceptance_mode else None,
        "actual_output_pages": output_page_count,
        "decision": "PASS",
    }
    if acceptance_mode and output_page_count != expected_pages:
        guard["decision"] = "PAGE_RANGE_SAFETY_ABORT"
        raise PageRangeSafetyAbort(
            f"PAGE_RANGE_SAFETY_ABORT expected={expected_pages} actual={output_page_count} "
            f"input={input_page_count} requested={requested or 'all'}"
        )

    record = {
        "input_page_count": input_page_count,
        "requested_page_ranges": requested,
        "selected_source_pages": [index + 1 for index in selected],
        "output_page_count": output_page_count,
        "page_range_safety_guard": guard,
        "page_records": page_records,
    }
    if output_page_count == 1:
        record.update(page_records[0])
    return b"".join(outputs), record


def encode_spl3(raster: bytes, args: list[str], options: str) -> tuple[bytes, dict]:
    """Encode final CUPS Raster with the frozen production SpliX filter."""
    high_quality = requested_resolution(options) == 1200
    quality = "Quality=1200dpi" if high_quality else "Quality=600dpi"
    encoder_options = " ".join([
        options,
        "PageSize=A4",
        "ColorModel=Gray",
        quality,
        "Duplex=None",
        "sides=one-sided",
        "DENSITY=3",
        "RET=NORMAL",
    ])
    with tempfile.NamedTemporaryFile(prefix="hp116w-final-raster-", suffix=".raster") as raster_file:
        raster_file.write(raster)
        raster_file.flush()
        command = [
            str(FROZEN_RASTERTOQPDL),
            args[0], args[1], args[2], args[3], encoder_options, raster_file.name,
        ]
        encoder_env = os.environ.copy()
        # The frozen SpliX 2.0.0 filter requires its matching production PPD.
        # It is read-only and never modified by this dispatcher.
        encoder_env["PPD"] = str(PROD_PPD)
        trace("RASTERTOQPDL_START", argv=" ".join(command), input_bytes=len(raster))
        started = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryFile() as error_stream:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_stream,
                                    env=encoder_env, close_fds=True)
            trace("RASTERTOQPDL_PID", pid_child=proc.pid)
            output_chunks: list[bytes] = []
            first_output_seen = threading.Event()

            def drain_encoder_stdout() -> None:
                assert proc.stdout is not None
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        return
                    if not first_output_seen.is_set():
                        first_output_seen.set()
                        trace("RASTERTOQPDL_FIRST_OUTPUT", output_bytes=len(chunk), first_output=True)
                    output_chunks.append(chunk)

            reader = threading.Thread(target=drain_encoder_stdout, name="hp116w-rastertoqpdl-reader")
            reader.start()
            proc.wait()
            reader.join()
            stdout_data = b"".join(output_chunks)
            completed = subprocess.CompletedProcess(command, proc.returncode, stdout=stdout_data)
            error_stream.seek(0)
            encoder_stderr = error_stream.read().decode("utf-8", "replace")
        if not first_output_seen.is_set():
            trace("RASTERTOQPDL_FIRST_OUTPUT", output_bytes=0, first_output=False)
        trace("RASTERTOQPDL_OUTPUT_BYTES", output_bytes=len(completed.stdout))
        trace("RASTERTOQPDL_EXIT_CODE", status=completed.returncode, exit_code=completed.returncode)
        trace("RASTERTOQPDL_EXIT", status=completed.returncode, exit_code=completed.returncode,
              stderr_bytes=len(encoder_stderr.encode("utf-8")), output_bytes=len(completed.stdout),
              elapsed_ms=int((dt.datetime.now(dt.timezone.utc)-started).total_seconds()*1000))
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, command)
    spl3 = completed.stdout
    required = [
        b"@PJL SET DUPLEX=OFF",
        b"@PJL SET DENSITY=3",
        b"@PJL SET RET=NORMAL",
        b"@PJL ENTER LANGUAGE = QPDL",
    ]
    if not spl3.startswith(b"\x1b%-12345X") or not all(token in spl3 for token in required):
        raise RuntimeError("invalid SPL3/PJL framing from frozen rastertoqpdl")
    return spl3, {
        "encoder": str(FROZEN_RASTERTOQPDL),
        "encoder_ppd": str(PROD_PPD),
        "encoder_options": encoder_options,
        "density": 3,
        "ret": "NORMAL",
        "duplex": "OFF",
        "compression": "0x11",
        "spl3_sha256": sha(spl3),
        "spl3_size_bytes": len(spl3),
        "encoder_stderr": encoder_stderr,
    }


def main() -> int:
    args=sys.argv[1:]
    if len(args) < 6: return 1
    global TRACE_JOB_ID, TRACE_FILE
    TRACE_JOB_ID = args[0]
    trace_root = Path(os.environ.get(
        "HP116W_TRACE_ROOT",
        "/private/var/spool/cups/tmp/hp116w-smart-dispatcher-traces",
    ))
    try:
        trace_dir = trace_root / str(args[0])
        trace_dir.mkdir(parents=True, exist_ok=True)
        TRACE_FILE = trace_dir / "dispatcher.trace"
    except OSError:
        TRACE_FILE = None
    trace("DISPATCHER_START", input=args[5], argv_count=len(args))
    trace("INPUT_OPEN_START", input=args[5])
    src=Path(args[5]) if len(args)>5 and args[5] != "-" else None
    data=src.read_bytes() if src else sys.stdin.buffer.read()
    trace("INPUT_OPEN_DONE", input=args[5], input_bytes=len(data), input_mode="filename" if src else "stdin")
    with tempfile.NamedTemporaryFile(prefix="hp116w-input-",suffix=".pdf",delete=False) as f: f.write(data); p=Path(f.name)
    # Strict macOS CUPS sandbox permits filter writes in the per-job TMPDIR,
    # but not in a root:wheel 0755 printer subtree.  Keep the default log
    # beside the job's private temporary files; callers may override this for
    # offline capture.  No document payload is logged.
    logdir=Path(os.environ.get("HP116W_DISPATCHER_LOG_DIR", str(p.parent / "hp116w-dispatcher-logs"))); logdir.mkdir(parents=True,exist_ok=True)
    dispatcher_status = "ok"
    try:
        options = args[4] if len(args) > 4 else ""
        raster,record=dispatch(p, options)
        trace("DISPATCH_COMPLETE", raster_bytes=len(raster))
        output_mode = os.environ.get("HP116W_DISPATCH_OUTPUT", runtime_config().get("cups_output", "spl3"))
        if output_mode == "raster":
            payload = raster
            record["cups_output"] = "application/vnd.cups-raster"
        elif output_mode == "spl3":
            payload, encoder_record = encode_spl3(raster, args, options)
            record["cups_output"] = "application/vnd.hp-spl3"
            record["spl3"] = encoder_record
        else:
            raise RuntimeError(f"unsupported HP116W_DISPATCH_OUTPUT: {output_mode}")
        trace("STDOUT_FIRST_WRITE", output_bytes=len(payload))
        sys.stdout.buffer.write(payload)
        trace("STDOUT_TOTAL_BYTES", output_bytes=len(payload))
        sys.stdout.buffer.flush()
        trace("STDOUT_FLUSH", output_bytes=len(payload))
        record.update({"timestamp":dt.datetime.now(dt.timezone.utc).isoformat(),"job_id":args[0],"user":args[1],"title":args[2],"copies":args[3],"input_sha256":sha(data),"final_raster_sha256":sha(raster),"output_sha256":sha(payload)})
        (logdir/f"job-{args[0]}.json").write_text(json.dumps(record,indent=2,default=str)+"\n")
    except (KeyboardInterrupt, SystemExit) as exc:
        dispatcher_status = "signal"
        trace("DISPATCHER_SIGNAL", status="signal", signal=type(exc).__name__)
        raise
    except Exception as exc:
        dispatcher_status = "error"
        decision = "PAGE_RANGE_SAFETY_ABORT" if isinstance(exc, PageRangeSafetyAbort) else "FILTER_RUNTIME_ABORT"
        trace("DISPATCHER_EXCEPTION", status="error", error=repr(exc), traceback=traceback.format_exc())
        record = {"timestamp":dt.datetime.now(dt.timezone.utc).isoformat(),"job_id":args[0],"user":args[1],"title":args[2],"copies":args[3],"input_sha256":sha(data),"decision":decision,"error":repr(exc)}
        (logdir/f"job-{args[0]}.json").write_text(json.dumps(record,indent=2,default=str)+"\n")
        print(f"ERROR: {decision}: {exc}", file=sys.stderr)
        return 1
    finally:
        trace("STDOUT_CLOSE", status="closed")
        trace("DISPATCHER_EXIT", status=dispatcher_status)
        p.unlink(missing_ok=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
