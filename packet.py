"""Multi-page packet analysis (100+ pages): every page is read, facts are extracted per page, and the same
fact is cross-checked across ALL pages. Every finding carries page citations (p.12, pp.40-42 ...)."""
import json
import re
from collections import Counter

from google.genai import types

import claimlogic as cl
import knowledge as kb
import policydb as pdb

EXPECTED_TYPES = {"claim_form": "claim form", "id_card": "ID proof", "discharge_summary": "discharge summary",
                  "medical_bill": "itemised bill"}

TYPE_KEYS = [
    ("discharge_summary", ["discharge summary"]),
    ("claim_form", ["claim form"]),
    ("id_card", ["aadhaar", "identity card", "id card", "driving licence", "driving license", "pan card", "passport", "voter"]),
    ("policy", ["policy schedule", "policy document", "schedule of benefits"]),
    ("medical_bill", ["final bill", "tax invoice", "invoice", "bill no", "pharmacy bill", "itemised bill", "itemized bill"]),
    ("lab_report", ["laboratory", "pathology", "radiology", "lab report"]),
    ("prescription", ["prescription"]),
]

PAGE_PROMPT = """You receive several consecutive pages of an insurance / loan packet. Each page starts with '--- Page N ---'.
Return ONLY JSON: {"pages": [one object PER PAGE, in order]}. Each object has exactly:
{"page": N, "patient_name": string|null, "policy_number": string|null, "address": string|null, "dob": string|null,
 "hospital": string|null, "dates": {"policy_start": string|null, "policy_end": string|null, "admission": string|null,
 "discharge": string|null, "bill_date": string|null, "claim_date": string|null},
 "items_detail": [{"desc": string, "amount": number}], "stated_total": number|null}
Use only what is printed on THAT page; null when absent; never guess. Dates exactly as written.
items_detail excludes totals and subtotals; stated_total is a grand total printed on that page."""


# ---------------------------------------------------------------- pages
def split_pages(text):
    parts = re.split(r"--- Page (\d+) ---", text)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def classify(text, prev):
    low = text.lower()
    for t, kws in TYPE_KEYS:
        if any(k in low for k in kws):
            return t
    if prev == "medical_bill" and re.search(r"(?:rs\.?|inr|₹)\s*[\d,]+", low):
        return "medical_bill"  # continuation page of a multi-page bill
    return "other"


def llm_page_facts(client, pages, progress=None, max_calls=30):
    """AI extraction in chunks of ~5 pages. Falls back to regex per page if the AI is unavailable."""
    facts, calls, err = {}, 0, None
    chunks, cur, size = [], [], 0
    for n, t in pages:
        if cur and (len(cur) >= 5 or size + min(len(t), 3500) > 9000):
            chunks.append(cur)
            cur, size = [], 0
        cur.append((n, t[:3500]))
        size += min(len(t), 3500)
    if cur:
        chunks.append(cur)
    use_ai = client is not None
    for i, ch in enumerate(chunks):
        if progress:
            progress(i, len(chunks), "Extracting facts")
        if use_ai and calls < max_calls:
            try:
                calls += 1
                r = client.models.generate_content(
                    model=cl.MODEL,
                    contents="\n".join(f"--- Page {n} ---\n{t}" for n, t in ch),
                    config=types.GenerateContentConfig(
                        system_instruction=PAGE_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
                for item in json.loads(r.text).get("pages", []):
                    facts[int(item.get("page"))] = cl.normalize_extraction(item)
            except Exception as e:
                err = type(e).__name__
                use_ai = False  # e.g. no credits: stop calling, use offline rules for the rest
        for n, t in ch:
            if n not in facts:
                facts[n] = cl.regex_extract(t)
    ai_pages = sum(1 for n, _ in pages if facts[n].get("summary") != "Offline rule-based extraction (less accurate than AI mode).")
    return facts, ai_pages, err


# ---------------------------------------------------------------- cross-page checks
def _clusters(vals, same):
    clusters = []
    for v, n in vals:
        for c in clusters:
            if same(c["rep"], v):
                c["pages"].append(n)
                c["vals"][v] += 1
                break
        else:
            clusters.append({"rep": v, "pages": [n], "vals": Counter({v: 1})})
    return clusters


def _same_dob(a, b):
    da, db = cl.parse_date(a), cl.parse_date(b)
    return da == db if (da and db) else str(a).strip() == str(b).strip()


IDENTITY = [  # field, label, same-cluster test, severity of a differing cluster
    ("patient_name", "Patient name", lambda a, b: cl.name_sim(a, b) >= 0.97,
     lambda m, c: "low" if cl.name_sim(m, c) >= 0.75 else "high"),
    ("policy_number", "Policy number", lambda a, b: cl._alnum(a) == cl._alnum(b), lambda m, c: "high"),
    ("dob", "Date of birth", _same_dob, lambda m, c: "high"),
    ("address", "Address", lambda a, b: cl.addr_sim(a, b) >= 0.5, lambda m, c: "high" if cl.addr_sim(m, c) < 0.25 else "low"),
]


def identity_checks(facts):
    flags, consensus = [], {}
    for field, label, same, sev_of in IDENTITY:
        vals = [(f[field], n) for n, f in sorted(facts.items()) if f.get(field)]
        clusters = _clusters(vals, same)
        if not clusters:
            continue
        main = max(clusters, key=lambda c: (len(c["pages"]), -min(c["pages"])))
        consensus[field] = (main["vals"].most_common(1)[0][0], sorted(main["pages"]))
        for c in clusters:
            if c is main:
                continue
            sev = sev_of(main["rep"], c["rep"])
            hint = " (spelling variation?)" if sev == "low" and field == "patient_name" else ""
            if field == "patient_name" and sev == "high":
                hint = " (a different person, or a nominee / guardian?)"
            flags.append({"sev": sev, "kind": "xpage", "pages": sorted(c["pages"]),
                          "msg": f"{label} '{c['vals'].most_common(1)[0][0]}' on {cl.fmt_pages(c['pages'])} differs from "
                                 f"'{consensus[field][0]}' on {cl.fmt_pages(main['pages'])}{hint}"})
    return flags, consensus


def date_checks(facts):
    """Consensus date per role (with pages), conflicts between pages, then the usual date-logic rules with citations."""
    flags, rd = [], {}
    roles = {}
    for n, f in sorted(facts.items()):
        for role, raw in (f.get("dates") or {}).items():
            d = cl.parse_date(raw)
            if d:
                roles.setdefault(role, {}).setdefault(d, []).append(n)
    for role, byd in roles.items():
        main = max(byd, key=lambda d: (len(byd[d]), -min(byd[d])))
        rd[role] = (main, sorted(byd[main]))
        for d, pg in byd.items():
            if d != main:
                flags.append({"sev": "high", "kind": "date", "pages": sorted(pg),
                              "msg": f"{role.replace('_', ' ').title()} date is {d} on {cl.fmt_pages(pg)} but {main} on {cl.fmt_pages(byd[main])}"})

    def cite(*rs):
        return cl.fmt_pages({p for r in rs if r in rd for p in rd[r][1]})

    def D(r):
        return rd[r][0] if r in rd else None

    adm, dis, pst, pen, bill, claim = D("admission"), D("discharge"), D("policy_start"), D("policy_end"), D("bill_date"), D("claim_date")
    rules = [
        (adm and dis and dis < adm, f"Discharge date ({dis}) is before admission date ({adm})", ("admission", "discharge")),
        (adm and pst and adm < pst, f"Admission ({adm}) is before the policy started ({pst})", ("admission", "policy_start")),
        (adm and pen and adm > pen, f"Admission ({adm}) is after the policy expired ({pen})", ("admission", "policy_end")),
        (bill and adm and bill < adm, f"Bill date ({bill}) is before admission date ({adm})", ("bill_date", "admission")),
        (claim and adm and claim < adm, f"Claim date ({claim}) is before treatment ({adm})", ("claim_date", "admission")),
    ]
    for cond, msg, rs in rules:
        if cond:
            flags.append({"sev": "high", "kind": "date", "pages": [], "msg": f"{msg} [{cite(*rs)}]"})
    import datetime as dt
    for r, (d, pg) in rd.items():
        if d > dt.date.today() and r != "policy_end":
            flags.append({"sev": "high", "kind": "date", "pages": pg, "msg": f"{r.replace('_', ' ').title()} ({d}) is in the future [{cl.fmt_pages(pg)}]"})
    return flags, rd


def bill_sections(pages, types):
    secs, cur = [], None
    for n, _ in pages:
        if types[n] == "medical_bill":
            if cur and cur["pages"][-1] == n - 1:
                cur["pages"].append(n)
            else:
                cur = {"pages": [n]}
                secs.append(cur)
    return secs


def math_checks(facts, secs):
    flags, items, totals = [], [], []
    for s in secs:
        s_items, s_total, s_tp = [], None, None
        for n in s["pages"]:
            for it in facts[n].get("items_detail") or []:
                s_items.append({"desc": it["desc"], "amount": it["amount"], "page": n})
            if facts[n].get("stated_total") is not None:
                s_total, s_tp = facts[n]["stated_total"], n
        items += s_items
        if s_total is not None:
            totals.append(s_total)
        if s_items and s_total is not None:
            tot = round(sum(i["amount"] for i in s_items), 2)
            if abs(tot - s_total) > 1:
                flags.append({"sev": "high", "kind": "math", "pages": s["pages"],
                              "msg": f"Bill on {cl.fmt_pages(s['pages'])}: line items add up to {tot:,.2f} but the stated total "
                                     f"(p.{s_tp}) is {s_total:,.2f} (difference {abs(tot - s_total):,.2f})"})
    return flags, items, totals


# ---------------------------------------------------------------- main entry
def analyze_packet(pages, client=None, progress=None):
    pages = sorted(pages)
    if client:
        facts, ai_pages, ai_err = llm_page_facts(client, pages, progress)
    else:
        facts = {}
        for i, (n, t) in enumerate(pages):
            facts[n] = cl.regex_extract(t)
            if progress and i % 10 == 0:
                progress(i, len(pages), "Extracting facts")
        ai_pages, ai_err = 0, None

    types, prev = {}, None
    for n, t in pages:
        types[n] = classify(t, prev)
        prev = types[n]
        facts[n]["doc_type"] = types[n]

    # packet map (consecutive pages of the same type)
    pmap = []
    for n, _ in pages:
        if pmap and pmap[-1][0] == types[n] and pmap[-1][2] == n - 1:
            pmap[-1][2] = n
        else:
            pmap.append([types[n], n, n])
    pmap = [tuple(x) for x in pmap]

    flags = []
    id_flags, consensus = identity_checks(facts)
    d_flags, rd = date_checks(facts)
    secs = bill_sections(pages, types)
    m_flags, items, totals = math_checks(facts, secs)
    flags += id_flags + d_flags + m_flags

    present = set(types.values())
    for t, label in EXPECTED_TYPES.items():
        if t not in present:
            flags.append({"sev": "low", "kind": "doc", "pages": [], "msg": f"No {label} found anywhere in the {len(pages)}-page packet"})

    hospital = next((facts[n]["hospital"] for n in sorted(facts) if facts[n].get("hospital")), None)
    data = {
        "doc_type": "packet",
        "patient_name": consensus.get("patient_name", (None,))[0], "policy_number": consensus.get("policy_number", (None,))[0],
        "dob": consensus.get("dob", (None,))[0], "address": consensus.get("address", (None,))[0], "hospital": hospital,
        "dates": {r: str(d) for r, (d, _) in rd.items()},
        "items_detail": items, "line_items": [i["amount"] for i in items],
        "stated_total": sum(totals) if totals else None,
        "red_flags": [], "llm_risk_score": None,
        "summary": f"{len(pages)}-page packet analysed page by page ({ai_pages} pages by AI, {len(pages) - ai_pages} by offline rules).",
    }

    db = pdb.verify_policy(data)
    tier = db["record"]["plan_tier"] if db["record"] else None
    rules = kb.check_items(data, tier)
    pol_pages = consensus.get("policy_number", (None, []))[1]
    adm_pages = rd["admission"][1] if "admission" in rd else []
    for f in db["flags"]:
        pg = adm_pages if re.search(r"treatment|waiting", f["msg"], re.I) else pol_pages
        if pg:
            f["msg"] += f" [{cl.fmt_pages(pg)}]"
    flags += db["flags"] + rules["flags"]
    flags.sort(key=lambda f: 0 if f["sev"] == "high" else 1)

    return {"pages": len(pages), "types": types, "map": pmap, "flags": flags, "data": data, "db": db, "kb": rules, "tier": tier,
            "facts": facts, "ai_pages": ai_pages, "ai_error": ai_err, "sections": [s["pages"] for s in secs],
            "consensus": {k: v for k, v in consensus.items()}}