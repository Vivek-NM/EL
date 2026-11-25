"""Rulebook knowledge base: retrieval (RAG) over documents in ./knowledge_base plus deterministic rule checks.
Drop your own rulebooks (.pdf / .txt / .md) into the folder and they are searched automatically.
All seeded numbers are ILLUSTRATIVE demo values: replace them with a real insurer's tariff sheet and terms."""
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

import fitz

KB_DIR = Path(__file__).parent / "knowledge_base"

SEED = {
    "plan_terms.md": """# Demo Health Plan Terms (illustrative)

## Basic plan
Sum insured up to Rs 2,00,000. Room rent is capped at 1% of the sum insured per day. Maternity, dental treatment, spectacles, cosmetic procedures, infertility treatment and vitamins or supplements are excluded.

## Silver plan
Sum insured up to Rs 3,00,000. Room rent is capped at 2% of the sum insured per day. Dental treatment, spectacles, cosmetic procedures, infertility treatment and vitamins or supplements are excluded. Maternity is covered after a 2-year waiting period.

## Gold plan
Sum insured up to Rs 5,00,000. Room rent is capped at 3% of the sum insured per day. Cosmetic procedures, spectacles, hearing aids and infertility treatment are excluded. Maternity is covered after a 1-year waiting period.

## Platinum plan
Sum insured up to Rs 10,00,000. No room rent cap for single private rooms. Only cosmetic procedures and experimental treatment are excluded.

## Waiting periods
An initial waiting period of 30 days from the policy start date applies to all illness claims. Accidents are covered from day one. Specific illnesses such as hernia, cataract and joint replacement carry a 2-year waiting period.

## Non-payable items
Registration and admission fees, service charges, gloves, masks, toiletries, attendant charges and similar consumables are commonly treated as non-payable by insurers.

## Overbilling and reasonable charges
Hospital charges above the reasonable and customary rate for the city and hospital category may be reduced to the benchmark amount. Charges more than 1.5 times the benchmark must be justified with a doctor's note.

## Claim document rules
The claim must include the discharge summary, itemised final bill and payment receipts. The patient name and policy number must match the policy schedule exactly.
""",
    "pricing_benchmarks.csv": """service,keywords,max_amount
Appendectomy,appendectomy|appendicectomy,90000
Cataract surgery,cataract,60000
Knee replacement,knee replacement,250000
Normal delivery,normal delivery,60000
Caesarean section,caesarean|c-section|cesarean,110000
MRI scan,mri,9000
CT scan,ct scan|ct-scan,6000
X-ray,x-ray|xray,800
ECG,ecg,500
Complete blood count,blood count|cbc,600
Ambulance,ambulance,3000
Specialist consultation,consultation,1500
Dialysis session,dialysis,3000
""",
    "plan_exclusions.json": json.dumps({
        "tiers": {
            "Basic": ["cosmetic", "dental", "spectacle", "maternity", "infertility", "vitamin", "supplement"],
            "Silver": ["cosmetic", "dental", "spectacle", "infertility", "vitamin", "supplement"],
            "Gold": ["cosmetic", "spectacle", "hearing aid", "infertility"],
            "Platinum": ["cosmetic", "experimental"],
        },
        "non_payable": ["registration", "admission fee", "service charge", "gloves", "mask", "toiletries", "attendant"],
    }, indent=2),
}


def ensure_kb():
    KB_DIR.mkdir(exist_ok=True)
    for name, content in SEED.items():
        p = KB_DIR / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- retrieval (BM25)
def _tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def _split(text, source, limit=900):
    chunks = []
    for block in re.split(r"\n(?=#)", text):  # split on markdown headings first
        block = block.strip()
        if not block:
            continue
        if len(block) <= limit:
            chunks.append((source, block))
            continue
        cur = ""
        for para in re.split(r"\n\s*\n", block):
            if len(cur) + len(para) > limit and cur:
                chunks.append((source, cur.strip()))
                cur = ""
            cur += para + "\n\n"
        if cur.strip():
            chunks.append((source, cur.strip()))
    return chunks


def load_chunks():
    ensure_kb()
    chunks = []
    for p in sorted(KB_DIR.iterdir()):
        try:
            if p.suffix.lower() in (".md", ".txt"):
                chunks += _split(p.read_text(encoding="utf-8", errors="ignore"), p.name)
            elif p.suffix.lower() == ".csv":
                rows = p.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]
                chunks += _split("\n\n".join(f"Benchmark {r.replace(',', ' | ')}" for r in rows), p.name)
            elif p.suffix.lower() == ".pdf":
                doc = fitz.open(p)
                for n, page in enumerate(doc, 1):
                    chunks += _split(page.get_text(), f"{p.name} p.{n}")
        except Exception:
            continue
    return chunks


_cache = {"key": None, "chunks": [], "tf": [], "df": Counter(), "avg": 1.0}


def _index():
    ensure_kb()
    key = tuple((p.name, p.stat().st_mtime) for p in sorted(KB_DIR.iterdir()))
    if _cache["key"] != key:
        chunks = load_chunks()
        tf = [Counter(_tok(t)) for _, t in chunks]
        df = Counter()
        for c in tf:
            df.update(c.keys())
        _cache.update(key=key, chunks=chunks, tf=tf, df=df, avg=(sum(sum(c.values()) for c in tf) / max(1, len(tf))) or 1.0)
    return _cache


def retrieve(query, k=3):
    """Top-k most relevant rulebook passages: [(source, text, score)]."""
    ix = _index()
    q = _tok(query)
    n = len(ix["chunks"])
    scored = []
    for i, c in enumerate(ix["tf"]):
        dl = sum(c.values()) or 1
        s = 0.0
        for t in set(q):
            if t in c:
                idf = math.log(1 + (n - ix["df"][t] + 0.5) / (ix["df"][t] + 0.5))
                s += idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * dl / ix["avg"]))
        if s > 0:
            scored.append((s, i))
    scored.sort(reverse=True)
    return [(ix["chunks"][i][0], ix["chunks"][i][1], round(s, 2)) for s, i in scored[:k]]


def files_in_kb():
    ensure_kb()
    ix = _index()
    counts = Counter(src.split(" p.")[0] for src, _ in ix["chunks"])
    return [(p.name, counts.get(p.name, 0)) for p in sorted(KB_DIR.iterdir())]


# ---------------------------------------------------------------- deterministic rule checks
def _has(desc, term):
    return re.search(r"\b" + re.escape(term.lower()), desc.lower()) is not None


def load_benchmarks():
    ensure_kb()
    out = []
    with open(KB_DIR / "pricing_benchmarks.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append((r["service"], [k.strip() for k in r["keywords"].split("|")], float(r["max_amount"])))
            except Exception:
                pass
    return out


def load_exclusions():
    ensure_kb()
    try:
        return json.loads((KB_DIR / "plan_exclusions.json").read_text(encoding="utf-8"))
    except Exception:
        return {"tiers": {}, "non_payable": []}


def check_items(data, tier):
    """Flags overpriced, excluded and non-payable line items. Returns {'flags','notes','queries'}."""
    flags, notes, queries = [], [], []
    items = data.get("items_detail") or []
    if not items:
        notes.append("No itemised charges were extracted, so price and exclusion checks were skipped.")
        return {"flags": flags, "notes": notes, "queries": queries}
    ex, bench = load_exclusions(), load_benchmarks()
    tiers = ex.get("tiers", {})
    if tier:
        excl = tiers.get(tier, [])
    else:  # unknown plan: only check what every plan excludes
        excl = sorted(set.intersection(*[set(v) for v in tiers.values()])) if tiers else []
        notes.append("Plan tier unknown (policy not found), so only exclusions common to all plans were checked.")
    for it in items:
        desc, amt = it["desc"], it["amount"]
        n0 = len(flags)
        hit = next((t for t in excl if _has(desc, t)), None)
        if hit:
            flags.append({"sev": "high", "kind": "kb", "msg": f"'{desc}' (Rs {amt:,.0f}) is excluded under {('the ' + tier + ' plan') if tier else 'all plans'} (matches '{hit}')"})
            queries.append(f"{tier} plan excluded {hit}")
        np_hit = next((t for t in ex.get("non_payable", []) if _has(desc, t)), None)
        if np_hit:
            flags.append({"sev": "low", "kind": "kb", "msg": f"'{desc}' (Rs {amt:,.0f}) is usually a non-payable item ('{np_hit}')"})
            queries.append("non-payable items " + np_hit)
        best = None
        for name, kws, mx in bench:
            for kw in kws:
                if _has(desc, kw) and (best is None or len(kw) > best[3]):
                    best = (name, kw, mx, len(kw))
        if best and amt > best[2]:
            ratio = amt / best[2]
            flags.append({"sev": "high" if ratio > 1.5 else "low", "kind": "kb",
                          "msg": f"'{desc}' billed Rs {amt:,.0f} vs benchmark maximum Rs {best[2]:,.0f} for {best[0]} ({ratio:.1f}x)"})
            queries.append("overbilling reasonable charges " + best[0])
        if it.get("page"):
            for f in flags[n0:]:
                f["msg"] += f" (p.{it['page']})"
    return {"flags": flags, "notes": notes, "queries": queries}


# ---------------------------------------------------------------- LLM answer grounded in the rulebook
def ask_rulebook(client, question, tier=None, k=4):
    """Returns (answer_or_None, passages). Without a client you still get the passages."""
    passages = retrieve(f"{question} {tier or ''}", k)
    if client is None or not passages:
        return None, passages
    ctx = "\n\n".join(f"[{s}]\n{t}" for s, t, _ in passages)
    prompt = (f"Answer the question using ONLY the rulebook excerpts below. Cite the source in brackets after each claim. "
              f"If the excerpts do not answer it, say so.\n\nExcerpts:\n{ctx}\n\nQuestion: {question}")
    from claimlogic import MODEL
    r = client.models.generate_content(model=MODEL, contents=prompt)
    return r.text, passages