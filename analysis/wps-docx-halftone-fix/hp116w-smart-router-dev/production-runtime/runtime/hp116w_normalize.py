#!/usr/bin/env python3
"""PDF input normalizer for the HP116W Smart Router.

Runs before cgpdftoraster, preserves vector PDF content, bypasses same-size
pages byte-for-byte, and normalizes only safe scale-1 content-fit mismatches.
It is deliberately not a production CUPS filter.
"""
from __future__ import annotations
import argparse, json, re, time
from pathlib import Path
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject

NUM = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

def path_content_bbox(data: bytes, page_w: float, page_h: float):
    """Estimate painted vector bbox; ignore Quartz's initial page clip rect."""
    tokens = re.split(rb"\s+", data); pending=[]; points=[]; first_clip=False
    # Track the affine CTM used by Quartz (often 0.05 scale + Y flip) so
    # outlined glyph coordinates are measured in page points, not device units.
    ctm=(1.,0.,0.,1.,0.,0.); stack=[]
    def mm(A,B):
        a,b,c,d,e,f=A; g,h,i,j,k,l=B
        return (a*g+c*h,b*g+d*h,a*i+c*j,b*i+d*j,a*k+c*l+e,b*k+d*l+f)
    def tx(p):
        a,b,c,d,e,f=ctm; x,y=p; return (a*x+c*y+e,b*x+d*y+f)
    ops={b"m":2,b"l":2,b"c":6,b"v":4,b"y":4,b"re":4}
    for tok in tokens:
        if not tok: continue
        if NUM.fullmatch(tok): pending.append(float(tok)); continue
        if tok == b"q": stack.append(ctm); pending=[]; continue
        if tok == b"Q": ctm=stack.pop() if stack else ctm; pending=[]; continue
        if tok == b"cm":
            if len(pending)>=6: ctm=mm(ctm,tuple(pending[-6:]))
            pending=[]; continue
        if tok in ops:
            n=ops[tok]
            if len(pending)>=n:
                a=pending[-n:]
                if tok==b"re" and a==[0.,0.,page_w,page_h]:
                    first_clip=True
                elif tok==b"re":
                    x,y,w,h=a; points += [tx((x,y)),tx((x+w,y)),tx((x,y+h)),tx((x+w,y+h))]
                elif tok==b"c": points += [tx((a[0],a[1])),tx((a[2],a[3])),tx((a[4],a[5]))]
                elif tok in (b"v",b"y"): points += [tx((a[0],a[1])),tx((a[-2],a[-1]))]
                else: points.append(tx((a[0],a[1])))
            pending=[]; continue
        pending=[]
    # Page-edge clipping/background paths are not document content.
    points=[(x,y) for x,y in points if 1e-4 < x < page_w-1e-4 and 1e-4 < y < page_h-1e-4]
    if not points: return None
    xs,ys=zip(*points); return [min(xs),min(ys),max(xs),max(ys)]

def apply_gray_curve(data: bytes, points):
    """Map neutral DeviceRGB vector `sc`/`rg` fills using monotonic data."""
    if not points: return data,0
    pts=sorted((float(a),float(b)) for a,b in points)
    def f(v):
        if v<=pts[0][0]: return pts[0][1]
        if v>=pts[-1][0]: return pts[-1][1]
        for (x0,y0),(x1,y1) in zip(pts,pts[1:]):
            if x0<=v<=x1: return y0+(v-x0)*(y1-y0)/(x1-x0)
        return v
    pat=re.compile(rb"(?P<a>[-+]?\d*\.\d+)\s+(?P<b>[-+]?\d*\.\d+)\s+(?P<c>[-+]?\d*\.\d+)\s+(?P<op>sc|rg)")
    changed=0
    def repl(m):
        nonlocal changed
        a,b,c=(float(m.group(k)) for k in ("a","b","c"))
        if max(a,b,c)-min(a,b,c)>1e-6: return m.group(0)
        v=a*255
        if v<pts[0][0] or v>pts[-1][0]: return m.group(0)
        o=max(0,min(255,f(v)))/255; s=f"{o:.7f}".encode("ascii"); changed+=1
        return s+b" "+s+b" "+s+b" "+m.group("op")
    return pat.sub(repl,data),changed

def normalize(src: Path, dst: Path, target_w: float, target_h: float, margins, gray_curve=None, tolerance=1.0):
    started=time.perf_counter(); reader=PdfReader(str(src)); writer=PdfWriter(); pages=[]; bypass=True
    if not gray_curve and all(abs(float(p.mediabox.width)-target_w)<=tolerance and abs(float(p.mediabox.height)-target_h)<=tolerance for p in reader.pages):
        # Transparent bypass: preserve bytes and metadata exactly.
        import shutil
        shutil.copyfile(src, dst)
        return {"input":str(src),"output":str(dst),"page_count":len(reader.pages),"bypass":True,
                "pages":[{"mode":"BYPASS","source_media_pt":[float(p.mediabox.width),float(p.mediabox.height)],"matrix":[1,0,0,1,0,0]} for p in reader.pages],"elapsed_ms":(time.perf_counter()-started)*1000}
    for page in reader.pages:
        sw,sh=float(page.mediabox.width),float(page.mediabox.height)
        same=abs(sw-target_w)<=tolerance and abs(sh-target_h)<=tolerance
        if same and not gray_curve:
            writer.add_page(page); pages.append({"mode":"BYPASS","source_media_pt":[sw,sh],"matrix":[1,0,0,1,0,0]}); continue
        bypass=False; contents=page.get_contents(); raw=contents.get_data() if contents is not None else b""; bbox=path_content_bbox(raw,sw,sh)
        if bbox is None:
            writer.add_page(page); pages.append({"mode":"BYPASS_UNSAFE","source_media_pt":[sw,sh]}); continue
        left,bottom,right,top=margins; bw,bh=bbox[2]-bbox[0],bbox[3]-bbox[1]; fits=bw<=right-left+1e-6 and bh<=top-bottom+1e-6
        if not fits:
            writer.add_page(page); pages.append({"mode":"FALLBACK_REQUIRED","content_bbox_pt":bbox,"scale":1.0}); continue
        count=0
        if gray_curve:
            replaced,count=apply_gray_curve(raw,gray_curve)
            if count:
                stream=DecodedStreamObject(); stream.set_data(replaced); page.replace_contents(stream)
        tx=(left+right)/2-(bbox[0]+bbox[2])/2; ty=top-sh
        out=writer.add_blank_page(width=target_w,height=target_h); out.merge_transformed_page(page,Transformation().translate(tx=tx,ty=ty))
        pages.append({"mode":"NORMALIZED","source_media_pt":[sw,sh],"target_media_pt":[target_w,target_h],"content_bbox_pt":bbox,"content_size_pt":[bw,bh],"fits_imageable":fits,"scale":1.0,"matrix":[1,0,0,1,tx,ty],"gray_replacements":count})
    with dst.open("wb") as f: writer.write(f)
    return {"input":str(src),"output":str(dst),"page_count":len(reader.pages),"bypass":bypass,"pages":pages,"elapsed_ms":(time.perf_counter()-started)*1000}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("input",type=Path); ap.add_argument("output",type=Path); ap.add_argument("--target",nargs=2,type=float,default=[595,842]); ap.add_argument("--margins",nargs=4,type=float,default=[12.5,12.5,582.5,829.5]); ap.add_argument("--curve",type=Path); ap.add_argument("--report",type=Path); a=ap.parse_args()
    curve=json.loads(a.curve.read_text()) if a.curve else None; r=normalize(a.input,a.output,a.target[0],a.target[1],a.margins,curve)
    if a.report: a.report.write_text(json.dumps(r,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(r,indent=2))
if __name__=="__main__": main()
