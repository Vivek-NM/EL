"""Core logic for ClaimGuard AI (no Streamlit code in here, so it is easy to test)."""
import io
import json
import os
import re
import datetime as dt
from difflib import SequenceMatcher

import fitz  # PyMuPDF
import numpy as np
import pytesseract
from dateutil import parser as dparser
from fpdf import FPDF
from google.genai import types
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
SUSPICIOUS_TOOLS = ["photoshop", "canva", "gimp", "illustrator", "pixlr", "paint", "editor"]

# ======================================================================
# 1. READING DOCUMENTS (text layer -> OCR fallback, embedded images, metadata)
# ======================================================================
def pdf_metadata_checks(doc):
    md = doc.metadata or {}
    out = []
    tools = (md.get("producer", "") + " " + md.get("creator", "")).lower()
    hit = [t for t in SUSPICIOUS_TOOLS if t in tools]
    if hit:
        out.append(("high", f"PDF was created/edited with editing software: {', '.join(hit)}"))
    c, m = md.get("creationDate", ""), md.get("modDate", "")
    if c and m and c != m:
        out.append(("low", f"PDF modified after creation (created {c[2:10]}, modified {m[2:10]})"))
    if not c:
        out.append(("low", "No creation date in PDF metadata (may have been stripped)"))
    return out


def fmt_pages(pages, limit=8):
    """[1,2,3,7,57] -> 'pp.1-3, 7, 57' (short page-citation string)."""
    ps = sorted({int(p) for p in pages})
    if not ps:
        return ""
    runs, start, prev = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start, prev))
        start = prev = p
    runs.append((start, prev))
    parts = [f"{a}" if a == b else f"{a}-{b}" for a, b in runs]
    extra = len(parts) - limit
    shown = ", ".join(parts[:limit]) + (f" (+{extra} more)" if extra > 0 else "")
    return ("p." if len(ps) == 1 else "pp.") + shown


def read_document(name, data, progress=None):
    """Returns (text, embedded_images[bytes], metadata_flags)."""
    ext = name.lower().rsplit(".", 1)[-1]
    text, images, meta = "", [], []
    try:
        if ext == "pdf":
            doc = fitz.open(stream=data, filetype="pdf")
            for n, page in enumerate(doc):
                t = page.get_text()
                if len(t.strip()) < 20:  # scanned page -> OCR
                    try:
                        pix = page.get_pixmap(dpi=200)
                        t = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))))
                    except Exception as e:
                        t = f"[OCR unavailable: {type(e).__name__}]"
                text += f"\n--- Page {n+1} ---\n{t}"
                if progress:
                    progress(n + 1, len(doc), "Reading pages")
                if len(images) < 12:  # keep memory small on 100+ page packets
                    for img in page.get_images(full=True):
                        try:
                            images.append(doc.extract_image(img[0])["image"])
                        except Exception:
                            pass
            meta = pdf_metadata_checks(doc)
        else:
            try:
                text = "\n--- Page 1 ---\n" + pytesseract.image_to_string(Image.open(io.BytesIO(data)))
            except Exception as e:
                text = f"[OCR unavailable: {type(e).__name__}]"
            images = [data]
            meta = image_meta_checks(data)
    except Exception as e:
        text = f"[Could not read file: {type(e).__name__}: {e}]"
    return text, images, meta


def ela_bytes(img_bytes, quality=90):
    """Error Level Analysis image (PNG bytes). Bright patches = regions that recompress differently."""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        diff = ImageChops.difference(img, Image.open(buf))
        mx = max(e[1] for e in diff.getextrema()) or 1
        out = io.BytesIO()
        ImageEnhance.Brightness(diff).enhance(255.0 / mx).save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


EDIT_TOOLS = SUSPICIOUS_TOOLS + ["lightroom", "affinity", "paint.net", "snapseed", "picsart", "pixelmator", "photopea"]


def image_meta_checks(img_bytes):
    """EXIF checks for an image file: editing software in the Software tag, modified after capture."""
    out = []
    try:
        ex = Image.open(io.BytesIO(img_bytes)).getexif()
        sw = str(ex.get(305, "") or "")
        if any(t in sw.lower() for t in EDIT_TOOLS):
            out.append(("high", f"Image was saved by editing software ({sw.strip()})"))
        taken = ex.get_ifd(0x8769).get(36867) if hasattr(ex, "get_ifd") else None
        modified = ex.get(306)
        if taken and modified and str(taken) != str(modified):
            out.append(("low", f"Image modified after it was captured (taken {taken}, modified {modified})"))
    except Exception:
        pass
    return out


def ela_analysis(img_bytes, quality=90, block=16):
    """Image tamper check. Returns the Error Level Analysis picture (for people to look at) plus an automatic verdict
    from a noise-consistency test: every real scan or photo carries a similar amount of sensor noise in its flat
    background. A patch that was erased and retyped has almost none, and a pasted patch from another image has a
    different amount. Blocks whose noise differs strongly from the rest of the page, in one compact group, are flagged.
    Returns {'png': bytes, 'suspicious': bool, 'score': float, 'box': (x0, y0, x1, y1) | None, 'detail': str}."""
    res = {"png": None, "suspicious": False, "score": 0.0, "box": None, "detail": "no anomaly found"}
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        scale = 1.0
        if max(img.size) > 1600:
            scale = 1600 / max(img.size)
            img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        diff = ImageChops.difference(img, Image.open(buf))
        mx = max(e[1] for e in diff.getextrema()) or 1
        out = io.BytesIO()
        ImageEnhance.Brightness(diff).enhance(255.0 / mx).save(out, "PNG")
        res["png"] = out.getvalue()

        gimg = img.convert("L")
        g = np.asarray(gimg, np.float32)
        blur_img = gimg.filter(ImageFilter.GaussianBlur(1.2))
        blur = np.asarray(blur_img, np.float32)
        resid = g - blur  # high-pass residual = noise
        gy, gx = np.gradient(blur)
        grad = np.hypot(gx, gy)
        hb, wb = g.shape[0] // block, g.shape[1] // block
        if hb < 6 or wb < 6:
            return res
        r = resid[:hb * block, :wb * block].reshape(hb, block, wb, block)
        nz = r.std(axis=(1, 3))
        flat = grad[:hb * block, :wb * block].reshape(hb, block, wb, block).max(axis=(1, 3)) < 4.0  # background-like blocks
        core = flat.copy()  # ignore blocks next to text or edges (JPEG ringing makes their noise unreliable)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                core &= np.roll(np.roll(flat, dy, axis=0), dx, axis=1)
        core[0, :] = core[-1, :] = False
        core[:, 0] = core[:, -1] = False
        flat = core
        if flat.sum() < 40:
            return res
        med = float(np.median(nz[flat]))
        thr = max(0.9, 0.4 * med)
        cand = flat & (np.abs(nz - med) > thr)
        if cand.sum() < 8 or cand.sum() > 0.25 * flat.sum():
            return res  # nothing, or a global property of the image rather than a local patch
        seen, best = np.zeros_like(cand), []
        for y, x in zip(*np.where(cand)):
            if seen[y, x]:
                continue
            stack, comp = [(y, x)], []
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                comp.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < hb and 0 <= nx < wb and cand[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            if len(comp) > len(best):
                best = comp
        if len(best) < 8:
            return res
        ys, xs = [c[0] for c in best], [c[1] for c in best]
        box = (int(min(xs) * block / scale), int(min(ys) * block / scale),
               int((max(xs) + 1) * block / scale), int((max(ys) + 1) * block / scale))
        lvl = float(np.mean([nz[y, x] for y, x in best]))
        res.update(suspicious=True, score=round(abs(lvl - med) / max(med, 0.3), 1), box=box,
                   detail=f"{len(best)} background blocks at x {box[0]}-{box[2]}, y {box[1]}-{box[3]} have "
                          f"{'much less' if lvl < med else 'much more'} scanner noise ({lvl:.1f} vs {med:.1f} elsewhere), "
                          f"typical of a retyped or pasted-in area")
    except Exception:
        pass
    return res


def mark_box(img_bytes, box, width=5):
    """The original image with the suspicious area outlined in red (PNG bytes)."""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        x0, y0, x1, y1 = box
        ImageDraw.Draw(img).rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), outline=(255, 40, 60), width=width)
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return img_bytes


def find_pages(text, value):
    """Page numbers where a value appears (used for citations)."""
    if not value:
        return []
    v = re.sub(r"\s+", " ", str(value)).strip().lower()
    pages = []
    parts = re.split(r"--- Page (\d+) ---", text)
    for i in range(1, len(parts) - 1, 2):
        if v in re.sub(r"\s+", " ", parts[i + 1]).lower():
            pages.append(int(parts[i]))
    return pages


# ======================================================================
# 2. STRUCTURED EXTRACTION (LLM first, rule-based fallback if no credits/key)
# ======================================================================
def _image_mime(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")


def llm_extract_multimodal(client, filename: str, raw_bytes: bytes, fallback_text: str = ""):
    """Extracts structured data directly from scanned/handwritten images or PDFs via Gemini vision."""
    mime = "application/pdf" if filename.lower().endswith(".pdf") else _image_mime(filename)
    doc_part = types.Part.from_bytes(data=raw_bytes, mime_type=mime)
    prompt = (
        "Read ALL printed and handwritten text on this document (including cursive, notes, tables, and stamps). "
        "Do not guess illegible handwriting—use null or '[illegible]' where unclear. "
        + (f"\nOCR/text-layer reference (verify visually):\n{fallback_text[:4000]}" if fallback_text.strip() else "")
    )
    r = client.models.generate_content(
        model=MODEL,
        contents=[doc_part, prompt],
        config=types.GenerateContentConfig(
            system_instruction=EXTRACT_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return normalize_extraction(json.loads(r.text))

EXTRACT_PROMPT = """You extract structured data from ONE insurance / loan / medical document.
Return ONLY a JSON object with exactly these keys:
{"doc_type": "id_card|medical_bill|discharge_summary|policy|claim_form|prescription|other",
 "patient_name": string|null, "policy_number": string|null, "address": string|null,
 "dob": string|null, "hospital": string|null,
 "dates": {"policy_start": string|null, "policy_end": string|null, "admission": string|null,
           "discharge": string|null, "bill_date": string|null, "claim_date": string|null},
 "items_detail": [{"desc": string, "amount": number}], "stated_total": number|null,
 "red_flags": [strings], "summary": "2 sentences", "llm_risk_score": integer 0-100}
Rules: use only information present in the text; use null when absent; never guess.
Dates exactly as written. items_detail = each individual charge with its description (exclude totals/subtotals); stated_total = the grand total printed on the document."""

DATE_PAT = r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4})"
ROLE_WORDS = {
    "policy_end": ["policy end", "valid till", "valid upto", "valid up to", "valid to", "expiry", "expires"],
    "policy_start": ["policy start", "valid from", "commencement", "inception"],
    "admission": ["admission", "admitted", "date of admission", "doa"],
    "discharge": ["discharge", "dod"],
    "bill_date": ["bill date", "invoice date", "date of bill", "bill dt"],
    "claim_date": ["claim date", "date of claim"],
}


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def normalize_extraction(d):
    base = {"doc_type": "other", "patient_name": None, "policy_number": None, "address": None, "dob": None,
            "hospital": None, "dates": {}, "line_items": [], "items_detail": [], "stated_total": None,
            "red_flags": [], "summary": "", "llm_risk_score": None}
    base.update({k: v for k, v in (d or {}).items() if k in base})
    if not isinstance(base["dates"], dict):
        base["dates"] = {}
    det = []
    for x in base["items_detail"] or []:
        if isinstance(x, dict) and _num(x.get("amount")) is not None:
            det.append({"desc": str(x.get("desc") or "item"), "amount": _num(x.get("amount"))})
    base["items_detail"] = det
    base["line_items"] = [n for n in (_num(x) for x in (base["line_items"] or [])) if n is not None]
    if det and not base["line_items"]:
        base["line_items"] = [x["amount"] for x in det]
    base["stated_total"] = _num(base["stated_total"])
    try:
        base["llm_risk_score"] = int(base["llm_risk_score"]) if base["llm_risk_score"] is not None else None
    except Exception:
        base["llm_risk_score"] = None
    if not isinstance(base["red_flags"], list):
        base["red_flags"] = []
    return base


def llm_extract(client, text):
    r = client.models.generate_content(
        model=MODEL,
        contents=text[:14000],
        config=types.GenerateContentConfig(
            system_instruction=EXTRACT_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return normalize_extraction(json.loads(r.text))


def regex_extract(text):
    """Rough offline extractor so the app still works without an API key / credits."""
    def first(pat):
        m = re.search(pat, text, re.I | re.M)
        return m.group(1).strip(" .,:;") if m else None

    low = text.lower()
    doc_type = "other"
    for t, kws in [("discharge_summary", ["discharge summary"]), ("medical_bill", ["invoice", "bill no", "final bill", "tax invoice"]),
                   ("id_card", ["aadhaar", "identity card", "id card", "driving licence", "pan card", "voter"]),
                   ("claim_form", ["claim form"]), ("policy", ["policy schedule", "policy document"])]:
        if any(k in low for k in kws):
            doc_type = t
            break

    dates = {}
    for line in text.splitlines():
        found = re.findall(DATE_PAT, line)
        if not found:
            continue
        ll = line.lower()
        if "policy period" in ll and len(found) >= 2:
            dates["policy_start"], dates["policy_end"] = found[0], found[1]
            continue
        for role, kws in ROLE_WORDS.items():
            if role not in dates and any(k in ll for k in kws):
                dates[role] = found[0]
                break

    items, detail, total = [], [], None
    cur = r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)"
    for line in text.splitlines():
        amts = re.findall(cur, line, re.I)
        if not amts:
            continue
        if re.search(r"total|net payable|amount payable|grand", line, re.I):
            total = _num(amts[-1])
        else:
            amt = _num(amts[-1])
            if amt is None:
                continue
            desc = re.split(r"(?:rs\.?|inr|₹)", line, 1, flags=re.I)[0].strip(" :-.\t0123456789")
            items.append(amt)
            detail.append({"desc": desc or "item", "amount": amt})

    return normalize_extraction({
        "doc_type": doc_type,
        "patient_name": first(r"^\s*(?:patient\s*name|name\s*of\s*patient|insured\s*name|policy\s*holder|name)\s*[:\-]\s*(.+)$"),
        "policy_number": first(r"policy\s*(?:no\.?|number|#|id)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{4,24})"),
        "address": first(r"^\s*address\s*[:\-]\s*(.+)$"),
        "dob": first(r"(?:dob|date of birth)\s*[:\-]?\s*" + DATE_PAT),
        "hospital": first(r"^\s*(?:hospital(?:\s*name)?)\s*[:\-]\s*(.+)$"),
        "dates": dates, "line_items": items, "items_detail": detail, "stated_total": total,
        "summary": "Offline rule-based extraction (less accurate than AI mode).",
    })


# ======================================================================
# 3. DETERMINISTIC CHECKS - math and dates are verified in Python, never trusted to the LLM
# ======================================================================
def parse_date(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        iso = re.match(r"^\d{4}-\d{1,2}-\d{1,2}", s) is not None  # ISO dates must not be read day-first
        return dparser.parse(s, dayfirst=not iso).date()
    except Exception:
        return None


def internal_checks(d):
    """Returns list of {'sev': 'high'|'low', 'kind': 'math'|'date'|'field', 'msg': str}."""
    flags = []
    dd = {k: parse_date(v) for k, v in (d.get("dates") or {}).items()}
    today = dt.date.today()

    # math
    items, total = d.get("line_items") or [], d.get("stated_total")
    if items and total is not None:
        s = round(sum(items), 2)
        if abs(s - total) > 1:
            flags.append({"sev": "high", "kind": "math",
                          "msg": f"Line items add up to {s:,.2f} but the stated total is {total:,.2f} (difference {abs(s-total):,.2f})"})

    # dates
    adm, dis, pst, pen = dd.get("admission"), dd.get("discharge"), dd.get("policy_start"), dd.get("policy_end")
    bill, claim = dd.get("bill_date"), dd.get("claim_date")
    if adm and dis and dis < adm:
        flags.append({"sev": "high", "kind": "date", "msg": f"Discharge date ({dis}) is before admission date ({adm})"})
    if adm and pst and adm < pst:
        flags.append({"sev": "high", "kind": "date", "msg": f"Admission ({adm}) is before the policy started ({pst})"})
    if adm and pen and adm > pen:
        flags.append({"sev": "high", "kind": "date", "msg": f"Admission ({adm}) is after the policy expired ({pen})"})
    if bill and adm and bill < adm:
        flags.append({"sev": "high", "kind": "date", "msg": f"Bill date ({bill}) is before admission date ({adm})"})
    if claim and adm and claim < adm:
        flags.append({"sev": "high", "kind": "date", "msg": f"Claim date ({claim}) is before treatment ({adm})"})
    for k, v in dd.items():
        if v and v > today and k != "policy_end":
            flags.append({"sev": "high", "kind": "date", "msg": f"{k.replace('_', ' ').title()} ({v}) is in the future"})

    # fields
    if not d.get("patient_name"):
        flags.append({"sev": "low", "kind": "field", "msg": "No patient / holder name found"})
    for f in d.get("red_flags") or []:
        flags.append({"sev": "low", "kind": "llm", "msg": f"AI: {f}"})
    return flags


# ======================================================================
# 4. MULTI-DOCUMENT CROSS-CHECK (names, policy numbers, addresses, DOB)
# ======================================================================
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "sri", "master", "late"}


def _name_norm(s):
    toks = [t for t in re.sub(r"[^a-z ]", " ", str(s).lower()).split() if t not in _TITLES]
    return " ".join(sorted(toks))


def name_sim(a, b):
    return SequenceMatcher(None, _name_norm(a), _name_norm(b)).ratio()


def _alnum(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def addr_sim(a, b):
    ta = {t for t in re.sub(r"[^a-z0-9 ]", " ", str(a).lower()).split() if len(t) > 2}
    tb = {t for t in re.sub(r"[^a-z0-9 ]", " ", str(b).lower()).split() if len(t) > 2}
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def cross_check(docs):
    """docs = [(filename, data)]. Compares every pair on every field both documents have."""
    out = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            (na, a), (nb, b) = docs[i], docs[j]
            pair = f"{na}  ↔  {nb}"
            if a.get("patient_name") and b.get("patient_name"):
                s = name_sim(a["patient_name"], b["patient_name"])
                st_ = "match" if s >= 0.97 else "warn" if s >= 0.75 else "mismatch"
                out.append({"pair": pair, "field": "Name", "a": a["patient_name"], "b": b["patient_name"], "status": st_,
                            "detail": f"similarity {s:.0%}"})
            if a.get("policy_number") and b.get("policy_number"):
                same = _alnum(a["policy_number"]) == _alnum(b["policy_number"])
                out.append({"pair": pair, "field": "Policy number", "a": a["policy_number"], "b": b["policy_number"],
                            "status": "match" if same else "mismatch", "detail": "exact match" if same else "numbers differ"})
            if a.get("address") and b.get("address"):
                s = addr_sim(a["address"], b["address"])
                st_ = "match" if s >= 0.5 else "warn" if s >= 0.25 else "mismatch"
                out.append({"pair": pair, "field": "Address", "a": a["address"], "b": b["address"], "status": st_,
                            "detail": f"token overlap {s:.0%}"})
            da, db = parse_date(a.get("dob")), parse_date(b.get("dob"))
            if da and db:
                out.append({"pair": pair, "field": "Date of birth", "a": str(da), "b": str(db),
                            "status": "match" if da == db else "mismatch", "detail": "same" if da == db else "dates differ"})
    return out


# ======================================================================
# 5. RISK SCORE: LLM baseline + rule penalties. Any hard mismatch forces the red zone.
# ======================================================================
LEVELS = [  # (min score, key, label, hex colour)
    (70, "red", "RED FLAG", "#ff4d6d"),
    (35, "yellow", "NEEDS REVIEW", "#ffb703"),
    (0, "green", "PASS", "#2ee59d"),
]


def compute_risk(docs, cross):
    """docs = list of dicts with 'name', 'data', 'flags'."""
    llm = [d["data"]["llm_risk_score"] for d in docs if d["data"].get("llm_risk_score") is not None]
    base = max(llm) if llm else 15
    score, hi, lo, hard = base, [], [], False
    for d in docs:
        for f in d["flags"]:
            if f["sev"] == "high":
                score += 20
                hard = True
                hi.append(f"[{d['name']}] {f['msg']}")
            elif f["kind"] in ("field", "db", "kb", "xpage", "doc"):
                score += 5
                lo.append(f"[{d['name']}] {f['msg']}")
        for tag in d.get("meta", []):
            if tag[0] == "high":
                score += 15
                hi.append(f"[{d['name']}] {tag[1]}")
            else:
                score += 3
                lo.append(f"[{d['name']}] {tag[1]}")
    for c in cross:
        if c["status"] == "mismatch":
            score += 25
            hard = True
            hi.append(f"Cross-check mismatch on {c['field']}: '{c['a']}' vs '{c['b']}'")
        elif c["status"] == "warn":
            score += 8
            lo.append(f"Cross-check partial match on {c['field']}: '{c['a']}' vs '{c['b']}' ({c['detail']})")
    reasons = hi + lo
    score = min(100, int(score))
    if hard:
        score = max(score, 70)  # dates or math or identity don't match -> automatic red zone
    for lo_, key, label, color in LEVELS:
        if score >= lo_:
            return {"score": score, "level": key, "label": label, "color": color, "reasons": reasons, "hard": hard}


# ======================================================================
# 6. EXPORT: executive summary (PDF) and plain-text report
# ======================================================================
METHOD = [
    ("1. Ingest", "Each page is read from the PDF text layer; scanned pages and images fall back to OCR (Tesseract)."),
    ("2. Extract", "An LLM (or an offline rule-based fallback) converts each document into a fixed schema: name, policy number, "
                   "address, DOB, dates, line items and stated total."),
    ("3. Look up & verify", "Python, not the LLM, recomputes the line-item sum and tests date logic (admission <= discharge, "
                            "treatment inside the policy period, no future dates). Numbers are never trusted on the model's word."),
    ("4. Cross-check", "Every pair of documents is compared on name (fuzzy), policy number (exact, normalised), address "
                       "(token overlap) and date of birth."),
    ("5. Forensics", "PDF metadata is audited for editing software and modification dates; embedded images get Error Level Analysis."),
    ("6. Score", "The LLM supplies a baseline risk score; rule penalties are added. Any hard mismatch (math, dates, identity) forces "
                 "the score into the red zone (>= 70). Bands: PASS < 35, NEEDS REVIEW 35-69, RED FLAG >= 70."),
    ("7. Human decision", "The output is decision support with page citations. A person makes the final approval."),
]


def _s(t):
    t = "-" if t is None else str(t)
    t = t.replace("↔", "<->").replace("–", "-").replace("—", "-").replace("•", "-").replace("’", "'")
    t = re.sub(r"(\S{70})", r"\1 ", t)
    return t.encode("latin-1", "replace").decode("latin-1")


def map_str(m):
    """Packet map -> 'claim form p.1; id card p.2; medical bill pp.110-111 ...'"""
    if not m:
        return ""
    known = [f"{t.replace('_', ' ')} {fmt_pages(range(a, b + 1))}" for t, a, b in m if t != "other"]
    other = sum(b - a + 1 for t, a, b in m if t == "other")
    return "; ".join(known) + (f"; {other} other/supporting pages" if other else "")


def build_report_dict(docs, cross, risk):
    ents = []
    for d in docs:
        x = d["data"]
        cites = {k: find_pages(d.get("text", ""), x.get(k)) for k in ("patient_name", "policy_number")}
        ents.append({"file": d["name"], "type": x.get("doc_type"), "name": x.get("patient_name"),
                     "policy": x.get("policy_number"), "address": x.get("address"), "dob": x.get("dob"),
                     "total": x.get("stated_total"), "summary": x.get("summary"), "pages": cites,
                     "flags": [f["msg"] for f in d["flags"]] + [m for _, m in d.get("meta", [])],
                     "map": (d.get("packet") or {}).get("map")})
    return {"generated": dt.datetime.now().strftime("%d %b %Y, %H:%M"), "risk": risk, "entities": ents, "cross": cross}


def build_text(rep):
    r = rep["risk"]
    L = ["CLAIMGUARD AI - EXECUTIVE SUMMARY", f"Generated: {rep['generated']}", "",
         f"VERDICT: {r['label']}   (risk score {r['score']}/100)", "", "KEY FINDINGS"]
    L += [f" - {x}" for x in r["reasons"]] or [" - No inconsistencies detected"]
    L += ["", "DOCUMENTS"]
    for e in rep["entities"]:
        pg = ", ".join(f"{k} {fmt_pages(v)}" for k, v in e["pages"].items() if v)
        if e.get("map"):
            L.append(f"   Packet map: {map_str(e['map'])}")
        L += [f" * {e['file']} ({e['type']})", f"     name={e['name']} | policy={e['policy']} | dob={e['dob']} | total={e['total']}"
              + (f" | cited: {pg}" if pg else "")]
    L += ["", "CROSS-DOCUMENT CHECKS"]
    L += [f" [{c['status'].upper()}] {c['field']}: {c['a']} vs {c['b']} ({c['detail']})" for c in rep["cross"]] or [" - n/a (single document)"]
    L += ["", "HOW THE VERIFICATION WORKS"] + [f" {a}: {b}" for a, b in METHOD]
    L += ["", "Decision support only; a human reviewer makes the final decision."]
    return "\n".join(L)


def build_pdf(rep) -> bytes:
    r = rep["risk"]
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 14)
    pdf.add_page()
    W = pdf.w - pdf.l_margin - pdf.r_margin

    def head(t):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(40, 30, 110)
        pdf.cell(0, 7, _s(t), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    def para(t, size=9.5, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(W, 4.8, _s(t), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "ClaimGuard AI - Executive Summary", new_x="LMARGIN", new_y="NEXT")
    para(f"Generated {rep['generated']}  |  Documents reviewed: {len(rep['entities'])}", 9)
    pdf.ln(2)

    rgb = tuple(int(r["color"][i:i + 2], 16) for i in (1, 3, 5))
    y = pdf.get_y()
    pdf.set_fill_color(*rgb)
    pdf.rect(pdf.l_margin, y, W, 16, "F")
    pdf.set_xy(pdf.l_margin + 4, y + 3)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 10, _s(f"{r['label']}  -  risk score {r['score']}/100"))
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(y + 19)

    head("Key findings")
    reasons = r["reasons"] or ["No inconsistencies detected."]
    for x in reasons[:10]:
        para("- " + x)
    if len(reasons) > 10:
        para(f"... and {len(reasons) - 10} more findings (see the TXT or JSON report).", 9, "I")

    head("Documents")
    for e in rep["entities"]:
        pg = ", ".join(f"{k.replace('_', ' ')} {fmt_pages(v)}" for k, v in e["pages"].items() if v)
        para(f"{e['file']} ({e['type']})", 9.5, "B")
        if e.get("map"):
            para("Packet map: " + map_str(e["map"]), 8.5, "I")
        para(f"Name: {e['name']} | Policy: {e['policy']} | DOB: {e['dob']} | Total: {e['total']}" + (f" | Cited: {pg}" if pg else ""), 9)

    head("Cross-document checks")
    if rep["cross"]:
        for c in rep["cross"]:
            para(f"[{c['status'].upper()}] {c['field']}: {c['a']}  vs  {c['b']}  ({c['detail']})", 9)
    else:
        para("Single document - upload two or more (e.g. ID card + bill) to enable cross-checking.", 9)

    head("How the verification logic works")
    for a, b in METHOD:
        para(f"{a}: {b}", 9)
    pdf.ln(2)
    para("Decision support only. A human reviewer makes the final decision.", 8.5, "I")
    return bytes(pdf.output())


# ======================================================================
# 7. FORM GUIDE: required documents + how to fill forms for the best approval chances
#    (general guidance for India; always confirm with your insurer/bank)
# ======================================================================
FORMS = {
    "Health insurance claim": {
        "docs": [
            ("Duly filled & signed claim form (Part A + hospital Part B)", ["claim form"]),
            ("Policy copy / health card / e-card", ["policy", "health card"]),
            ("Photo ID of patient (Aadhaar / PAN / passport)", ["aadhaar", "pan", "identity", "id card", "passport"]),
            ("Discharge summary", ["discharge summary"]),
            ("Original itemised hospital bills + final bill", ["invoice", "final bill", "bill no"]),
            ("Payment receipts", ["receipt"]),
            ("Pharmacy bills with matching prescriptions", ["pharmacy", "prescription"]),
            ("Diagnostic / lab / radiology reports", ["report", "lab", "radiology", "pathology"]),
            ("Doctor's admission note / referral", ["admission note", "referral"]),
            ("Cancelled cheque / bank details of claimant", ["cancelled cheque", "ifsc"]),
            ("FIR / MLC copy (only if accident or injury)", ["fir", "mlc"]),
        ],
        "fill": [
            "Write the patient's name EXACTLY as on the policy and ID card; no nicknames or initials unless the policy uses them.",
            "Copy the policy number character by character from the policy schedule.",
            "Use the same date format everywhere and double-check admission < discharge and both fall inside the policy period.",
            "Describe the diagnosis using the discharge summary's wording, and list the treating doctor's registration number.",
            "Claimed amount must equal the total on the final bill; do not round off. Attach the bill breakup.",
            "Sign wherever marked. Do not use correction fluid or overwrite; strike once and initial a correction.",
        ],
        "mistakes": ["Name or policy number differs between documents", "Missing discharge summary or itemised bill",
                     "Photocopied bills where originals were required", "Claim filed after the notification window",
                     "Illegible scans or cropped pages", "Pre-existing condition not disclosed on the proposal form"],
    },
    "Motor insurance claim": {
        "docs": [
            ("Claim form signed by the insured", ["claim form"]),
            ("Policy copy / cover note", ["policy"]),
            ("Registration certificate (RC)", ["registration certificate", "rc book"]),
            ("Driving licence of the driver at the time of accident", ["driving licence", "driving license"]),
            ("Photos of damage (all sides + chassis number)", ["photo"]),
            ("Repair estimate and final repair invoice", ["estimate", "invoice"]),
            ("FIR copy (theft, third-party injury or major accident)", ["fir"]),
            ("Surveyor report (if assigned)", ["survey"]),
            ("ID proof and cancelled cheque of the owner", ["aadhaar", "pan", "cancelled cheque"]),
        ],
        "fill": [
            "Report the incident to the insurer immediately and state date, time and place consistently in every document.",
            "The registration number and chassis/engine number must match the RC exactly.",
            "Describe the accident factually in 3-5 lines; avoid speculation about fault.",
            "Do not start repairs before the surveyor inspection unless the insurer allows it.",
        ],
        "mistakes": ["Accident date/time differs between FIR and claim form", "Driver without a valid licence",
                     "Repairs done before inspection", "Late intimation"],
    },
    "Life insurance claim": {
        "docs": [
            ("Claim form (claimant's statement)", ["claim form"]),
            ("Original policy document", ["policy"]),
            ("Death certificate (issued by municipal authority)", ["death certificate"]),
            ("Nominee's ID, address proof and KYC", ["aadhaar", "pan", "kyc"]),
            ("Cancelled cheque / bank details of nominee", ["cancelled cheque", "ifsc"]),
            ("Medical records / hospital treatment papers", ["discharge summary", "medical record"]),
            ("FIR + post-mortem report (unnatural death)", ["fir", "post-mortem", "postmortem"]),
        ],
        "fill": [
            "Nominee details on the form must match the policy's nominee exactly.",
            "Give the cause and date of death exactly as on the death certificate.",
            "If death occurred within the first 2-3 years of the policy, expect extra scrutiny: have complete medical history ready.",
        ],
        "mistakes": ["Nominee name mismatch", "Non-disclosure of medical history in the proposal", "Missing death certificate"],
    },
    "Home loan": {
        "docs": [
            ("Completed loan application form with photographs", ["application form"]),
            ("Identity proof (Aadhaar / PAN / passport)", ["aadhaar", "pan", "passport"]),
            ("Address proof", ["address proof", "utility bill", "aadhaar"]),
            ("Income proof: last 3 months' salary slips", ["salary slip", "payslip"]),
            ("Form 16 / ITR for the last 2-3 years", ["form 16", "itr"]),
            ("Bank statements (last 6 months)", ["bank statement"]),
            ("Employment proof (offer letter / employee ID)", ["offer letter", "employee id"]),
            ("Property documents (sale agreement, title deed, approved plan)", ["sale agreement", "title deed"]),
            ("Processing fee cheque", ["cheque"]),
        ],
        "fill": [
            "Use the same name, address and employer details across the form, ID, salary slips and bank statements.",
            "Declare ALL existing loans and EMIs; lenders see them on your credit report anyway.",
            "Make sure salary credits in the bank statement match the salary slips.",
            "Check your credit score first; clear any overdue card payments before applying.",
        ],
        "mistakes": ["Undisclosed existing EMIs", "Income on slips differs from bank credits", "Address mismatch across documents",
                     "Many recent loan enquiries on credit report", "Unclear property title"],
    },
    "Personal loan": {
        "docs": [
            ("Application form with photograph", ["application form"]),
            ("Identity proof", ["aadhaar", "pan", "passport"]),
            ("Address proof", ["address proof", "utility bill", "aadhaar"]),
            ("Last 3 months' salary slips", ["salary slip", "payslip"]),
            ("Bank statements (last 3-6 months)", ["bank statement"]),
            ("Employment proof", ["offer letter", "employee id"]),
        ],
        "fill": [
            "Keep the requested amount realistic: EMIs should stay well under about 40-50% of monthly income.",
            "State the loan purpose clearly and consistently.",
            "Use the employer name exactly as on the salary slip.",
        ],
        "mistakes": ["Low credit score", "Frequent job changes not explained", "Income and EMI burden too high"],
    },
    "Education loan": {
        "docs": [
            ("Application form with photographs", ["application form"]),
            ("Admission letter from the institution", ["admission letter", "offer of admission"]),
            ("Fee structure / cost breakup", ["fee structure"]),
            ("Previous academic marksheets", ["marksheet", "mark sheet"]),
            ("Student ID and address proof", ["aadhaar", "pan", "passport"]),
            ("Co-borrower ID, address and income proof", ["salary slip", "itr", "form 16"]),
            ("Co-borrower bank statements (6 months)", ["bank statement"]),
            ("Collateral documents (if the loan amount needs it)", ["collateral", "title deed"]),
        ],
        "fill": [
            "Ensure the fee structure covers every item you are asking the loan for (tuition, hostel, books, laptop).",
            "Co-borrower details (name, PAN, income) must match their documents exactly.",
            "Ask the bank about subsidy / interest-moratorium schemes you may qualify for.",
        ],
        "mistakes": ["Co-borrower with weak income or credit history", "Loan amount above documented costs", "Missing admission proof"],
    },
}

APPROVAL_TIPS = [
    "Consistency beats everything: names, policy/loan numbers, addresses and dates must be identical across every document.",
    "Submit a complete packet in one go; incomplete packets are the #1 cause of delays and rejections.",
    "Scan flat, in colour, at 200+ dpi, every page, nothing cropped. Name files clearly (e.g. 01_claim_form.pdf).",
    "Meet deadlines: notify your insurer or bank early and keep proof of submission and the reference number.",
    "Disclose everything asked (medical history, existing loans). Non-disclosure is the most common reason for later rejection.",
    "Keep copies of everything and answer follow-up queries within 24-48 hours.",
    "Run your packet through ClaimGuard first: fix any red flags before the real reviewer sees them.",
]


def ai_form_advice(client, form_name, extracted, missing):
    prompt = (f"A person is preparing a '{form_name}' application in India. Extracted data from their documents: "
              f"{json.dumps(extracted)[:3000]}\nDocuments still missing: {missing}\n"
              "Give 5-7 short, concrete, personalised suggestions to maximise approval chances: fields to double-check, "
              "inconsistencies to fix, documents to add. Be practical; do not promise approval.")
    r = client.models.generate_content(model=MODEL, contents=prompt)
    return r.text