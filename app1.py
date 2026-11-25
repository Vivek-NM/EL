import colorsys
import json
import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
"""from google import genai"""

import claimlogic as cl
import knowledge as kb
import packet
import policydb as pdb

st.set_page_config(page_title="ClaimGuard AI", page_icon="🛡️", layout="wide")

# ====================================================================== THEMES
THEMES = {
    "Midnight Ocean": dict(bg=["#021027", "#03306b", "#05476f", "#021b3a", "#06304f"], orbs=("#00b4d8", "#4361ee"),
                           acc=("#48cae4", "#4895ef", "#90e0ef")),
    "Emerald Night": dict(bg=["#021b17", "#064e3b", "#0b3b3c", "#022c22", "#0f3d2e"], orbs=("#2ee59d", "#00b4d8"),
                          acc=("#2ee59d", "#00c2a8", "#a7ffeb")),
    "Sunset": dict(bg=["#2b0a3d", "#5a1a4a", "#7a2a3a", "#3d1450", "#4a1230"], orbs=("#ff9e00", "#ff2e63"),
                   acc=("#ffb703", "#ff6b6b", "#ff2e63")),
    "Royal Gold": dict(bg=["#120e07", "#2b2110", "#3a2a0e", "#1c1608", "#33250a"], orbs=("#ffd166", "#ef476f"),
                       acc=("#ffd166", "#f4a261", "#ef476f")),
    "Aurora (original)": dict(bg=["#0f0c29", "#302b63", "#24243e", "#0b3d5c", "#1a0b3d"], orbs=("#00e5ff", "#ff2fd2"),
                              acc=("#00e5ff", "#a855f7", "#ff2fd2")),
}


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hex(r, g, b):
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, v)) * 255) for v in (r, g, b))


def shade(h, k):
    r, g, b = _rgb(h)
    return _hex(r * k, g * k, b * k)


def hue(h, d):
    r, g, b = _rgb(h)
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    return _hex(*colorsys.hls_to_rgb((hh + d) % 1, l, s))


with st.sidebar:
    st.markdown("### 🎨 Theme")
    theme_name = st.selectbox("Colour theme", list(THEMES) + ["Custom"], index=0)
    if theme_name == "Custom":
        base = st.color_picker("Background colour", "#1e3a5f")
        accent = st.color_picker("Accent colour", "#4cc9f0")
        TH = dict(bg=[shade(base, .3), shade(base, .6), base, shade(base, .45), shade(base, .25)],
                  orbs=(accent, hue(accent, .12)), acc=(accent, hue(accent, .08), hue(accent, .2)))
    else:
        TH = THEMES[theme_name]
    st.caption("Add your own pictures to the `assets/` folder (png, jpg, webp) and they appear in the gallery automatically.")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif; }
.stApp { background: linear-gradient(-45deg,@B1@,@B2@,@B3@,@B4@,@B5@); background-size:400% 400%;
  animation: gradientBG 18s ease infinite; color:#e8e8ff; }
@keyframes gradientBG {0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.stApp::before,.stApp::after{content:"";position:fixed;border-radius:50%;filter:blur(90px);z-index:0;pointer-events:none;opacity:.4}
.stApp::before{width:420px;height:420px;background:@O1@;top:-120px;left:-100px;animation:f1 14s ease-in-out infinite}
.stApp::after{width:460px;height:460px;background:@O2@;bottom:-140px;right:-120px;animation:f2 17s ease-in-out infinite}
@keyframes f1{50%{transform:translate(120px,80px)}} @keyframes f2{50%{transform:translate(-140px,-90px)}}
header[data-testid="stHeader"]{background:transparent}
section[data-testid="stSidebar"]{background:rgba(10,10,30,.55);backdrop-filter:blur(12px)}
section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] label p,section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#e8e8ff !important}
.stApp h1,.stApp h2,.stApp h3,.stApp h4,[data-testid="stWidgetLabel"] p,button[data-baseweb="tab"] p{color:#e8e8ff !important}
.stApp [data-testid="stCaptionContainer"]{color:#b9b8e6 !important}
.hero h1{font-size:3rem;font-weight:700;background:linear-gradient(90deg,@A1@,@A2@,@A3@);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.glass{background:rgba(255,255,255,.06);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.15);
  border-radius:18px;padding:1.2rem 1.4rem;margin-bottom:1rem;box-shadow:0 8px 32px rgba(0,0,0,.35)}
.gauge{width:190px;height:190px;border-radius:50%;margin:auto;display:flex;align-items:center;justify-content:center;
  background:conic-gradient(var(--c) calc(var(--v)*1%),rgba(255,255,255,.1) 0)}
.gauge div{width:150px;height:150px;border-radius:50%;background:#16143a;display:flex;flex-direction:column;
  align-items:center;justify-content:center;font-size:2.4rem;font-weight:700}
.gauge small{font-size:.8rem;opacity:.7;font-weight:400}
.badge{display:block;text-align:center;margin:1rem auto 0;padding:.5rem 1.2rem;border-radius:999px;font-weight:700;
  color:#14122e;letter-spacing:.06em;width:fit-content;box-shadow:0 0 25px var(--b)}
.flag{border-left:4px solid #ff4d6d;padding:.4rem .8rem;margin:.4rem 0;background:rgba(255,77,109,.12);border-radius:6px}
.warn{border-left:4px solid #ffb703;padding:.4rem .8rem;margin:.4rem 0;background:rgba(255,183,3,.12);border-radius:6px}
.ok{border-left:4px solid #2ee59d;padding:.4rem .8rem;margin:.4rem 0;background:rgba(46,229,157,.12);border-radius:6px}
.src{border-left:4px solid @A1@;padding:.4rem .8rem;margin:.4rem 0;background:rgba(255,255,255,.05);border-radius:6px;font-size:.92rem}
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{background:linear-gradient(90deg,@A1@,@A2@);color:#fff;border:0;
  border-radius:12px;padding:.6rem 1.4rem;font-weight:600;transition:.25s}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-2px) scale(1.03);box-shadow:0 0 25px @A2@}
</style>
"""
for tok, val in zip(["@B1@", "@B2@", "@B3@", "@B4@", "@B5@"], TH["bg"]):
    CSS = CSS.replace(tok, val)
CSS = CSS.replace("@O1@", TH["orbs"][0]).replace("@O2@", TH["orbs"][1])
for tok, val in zip(["@A1@", "@A2@", "@A3@"], TH["acc"]):
    CSS = CSS.replace(tok, val)
st.markdown(CSS, unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>🛡️ ClaimGuard AI</h1></div>', unsafe_allow_html=True)
st.caption("OCR • Policy database • Rulebook RAG • Forensics • Multi-document cross-checking • Explainable risk scoring")

try:
    from landing import render_landing
    try:
        render_landing(TH["acc"])
    except TypeError:  # an older landing.py without theme support
        render_landing()
except ImportError:
    pass


# ====================================================================== API CLIENT
def get_key():
    k = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if k:
        return k
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


key = get_key()
client = genai.Client(api_key=key) if key else None
pdb.ensure_db()
kb.ensure_kb()



def run_analysis(files, packet_mode=True):
    docs = []
    bar = st.progress(0.0, text="Starting...")

    for f in files:
        raw_bytes = f.getvalue()

        def cb(done, total, msg="Working"):
            bar.progress(
                min(1.0, done / max(1, total)),
                text=f"{f.name}: {msg} ({done}/{total})"
            )

        # 1. Read the document locally first.
        text, images, meta = cl.read_document(
            f.name, raw_bytes, cb
        )

        pages = packet.split_pages(text)
        pk = None
        used_ai = False
        err = None

        # 2. Large multi-page packets use the packet pipeline.
        if packet_mode and len(pages) >= 5:
            pk = packet.analyze_packet(pages, client, cb)

            data = pk["data"]
            db = pk["db"]
            rules = pk["kb"]
            tier = pk["tier"]

            flags = pk["flags"]
            used_ai = pk["ai_pages"] > 0
            err = pk["ai_error"]

        else:
            # 3. Normal images and smaller PDFs go through Gemini Vision.
            data = None

            if client:
                try:
                    with st.spinner(f"Gemini is visually analysing {f.name}..."):
                        data = cl.llm_extract_multimodal(
                            client=client,
                            filename=f.name,
                            raw_bytes=raw_bytes,
                            fallback_text=text
                        )
                    used_ai = True

                except Exception as vision_error:
                    err = (
                        f"Vision: {type(vision_error).__name__}"
                    )

                    # 4. If vision fails, try the extracted text.
                    if text.strip() and not text.startswith("[Could not read"):
                        try:
                            data = cl.llm_extract(client, text)
                            used_ai = True
                        except Exception as text_error:
                            err += (
                                f"; Text AI: {type(text_error).__name__}"
                            )

            # 5. Final fallback: local rule-based extraction.
            if data is None:
                data = cl.regex_extract(text)

            # 6. Run deterministic checks.
            db = pdb.verify_policy(data)

            tier = (
                db["record"]["plan_tier"]
                if db["record"]
                else None
            )

            rules = kb.check_items(data, tier)

            flags = (
                cl.internal_checks(data)
                + db["flags"]
                + rules["flags"]
            )

        # 7. Image forensics.
        analyses = [
            cl.ela_analysis(i)
            for i in images[:4]
        ]

        is_image_file = f.name.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        )

        for k, a in enumerate(analyses, 1):
            if a["suspicious"]:
                where = (
                    "Uploaded image"
                    if is_image_file
                    else f"Embedded image {k}"
                )

                flags.append({
                    "sev": "high",
                    "kind": "forensic",
                    "msg": (
                        f"{where}: possible edit. "
                        f"{a['detail']}"
                    )
                })

        # 8. Save the document analysis.
        docs.append({
            "name": f.name,
            "data": data,
            "text": text,
            "meta": meta,
            "db": db,
            "kb": rules,
            "tier": tier,
            "flags": flags,
            "packet": pk,
            "images": [
                (
                    cl.mark_box(i, a["box"])
                    if a["suspicious"] and a["box"]
                    else i,
                    a["png"],
                    a
                )
                for i, a in zip(images[:4], analyses)
            ],
            "used_ai": used_ai,
            "ai_error": err
        })

    bar.empty()

    # 9. Cross-document verification.
    cross = cl.cross_check([
        (d["name"], d["data"])
        for d in docs
    ])

    # 10. Final risk calculation.
    risk = cl.compute_risk(docs, cross)

    return {
        "docs": docs,
        "cross": cross,
        "risk": risk,
        "id": st.session_state.get("aid", 0) + 1
    }



@st.cache_data(show_spinner=False)
def packet_demo(tampered):
    return pdb.sample_packet_pdf(tampered)


def stretch(fn, *a, **kw):
    """Full-width elements on both old and new Streamlit versions."""
    try:
        return fn(*a, width="stretch", **kw)
    except Exception:
        return fn(*a, use_container_width=True, **kw)


def gauge(score, color):
    st.markdown(f'<div class="gauge" style="--v:{score};--c:{color}"><div>{score}<small>RISK / 100</small></div></div>',
                unsafe_allow_html=True)


def line(kind, icon, text):
    st.markdown(f'<div class="{kind}">{icon} {text}</div>', unsafe_allow_html=True)


def show_passages(passages):
    for src, txt, _ in passages:
        snippet = txt.replace("\n", " ")
        st.markdown(f'<div class="src"><b>📖 {src}</b><br>{snippet[:420]}{"…" if len(snippet) > 420 else ""}</div>',
                    unsafe_allow_html=True)


st.markdown('<div id="tool"></div>', unsafe_allow_html=True)
tab_verify, tab_guide, tab_db, tab_kb = st.tabs(["🔍 Verify documents", "📋 Form guide", "🗄️ Policy database", "📚 Rulebook (RAG)"])

# ====================================================================== TAB 1: VERIFY
with tab_verify:
    if client:
        st.info("AI mode on. If Gemini is unavailable (e.g. quota/key issue) the app falls back to offline rule-based extraction.")
    else:
        st.warning("No GEMINI_API_KEY found: running in offline rule-based mode. Every check still works; extraction is just less accurate.")

    with st.expander("🧪 Try the demo documents (they match the demo policy database)"):
        st.caption("Upload the ID card together with either bill. The genuine bill passes; the tampered one trips the policy lookup, "
                   "date, math, price and exclusion checks. The 'wrong person' ID card fails the cross-document check against the genuine bill.")
        s1, s2, s3, s4 = st.columns(4)
        for col, (fname, label) in zip((s1, s2, s3, s4), [("genuine_bill.pdf", "✅ Genuine bill"), ("tampered_bill.pdf", "🚩 Tampered bill"),
                                                          ("id_card.pdf", "🪪 ID card"), ("id_card_mismatch.pdf", "🪪 ID card (wrong person)")]):
            col.download_button(label, pdb.sample_pdf(fname), fname, "application/pdf", key="sample_" + fname)
        st.caption("**100+ page packets:** inconsistencies hidden deep in the file (different name on one page, different policy number "
                   "on another, conflicting discharge date, an excluded item, a bad total). Findings cite the page numbers.")
        p1, p2 = st.columns(2)
        p1.download_button("📚 120-page packet (tampered)", packet_demo(True), "packet_tampered_120pp.pdf", "application/pdf", key="pk_t")
        p2.download_button("📚 120-page packet (clean)", packet_demo(False), "packet_clean_120pp.pdf", "application/pdf", key="pk_c")
        demo_dir = Path(__file__).parent / "demo_files"
        if demo_dir.exists():
            st.markdown("**🖼️ Image-tampering demos** (scans and claim packs; the `scan_*_genuine` / `claim_pack_genuine` files are clean)")
            demo_files = sorted(p for p in demo_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".pdf"))
            cols = st.columns(3)
            for i, p in enumerate(demo_files):
                mime = "application/pdf" if p.suffix.lower() == ".pdf" else "image/jpeg"
                cols[i % 3].download_button(p.name, p.read_bytes(), p.name, mime, key="demo_" + p.name)

    files = st.file_uploader("Upload one or more documents (e.g. ID card + medical bill) to cross-check them",
                             type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

    packet_mode = st.checkbox("📚 Packet mode: analyse PDFs with 5+ pages page by page, cross-check every page and cite page numbers",
                              value=True)
    st.caption("Scanned (image-only) pages need OCR, which takes a few seconds per page, so a scanned 100-page packet can take several minutes.")

    if files and st.button("🚀 Run verification"):
        with st.spinner("Reading, extracting, checking the policy database and rulebook, scoring..."):
            res = run_analysis(files, packet_mode)
            st.session_state["aid"] = res["id"]
            st.session_state["analysis"] = res

    res = st.session_state.get("analysis")
    if res:
        risk, docs, cross = res["risk"], res["docs"], res["cross"]
        for d in docs:
            if d["ai_error"]:
                st.warning(f"{d['name']}: AI extraction failed ({d['ai_error']}), used offline extraction instead.")

        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown('<div class="glass">', unsafe_allow_html=True)
            gauge(risk["score"], risk["color"])
            st.markdown(f'<span class="badge" style="background:{risk["color"]};--b:{risk["color"]}">{risk["label"]}</span>',
                        unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        with c2:
            st.markdown("### Why this score")
            if risk["hard"]:
                line("flag", "🚩", "A date, math, identity, policy or rulebook check failed, so the score was moved into the red zone automatically.")
            if not risk["reasons"]:
                line("ok", "✅", "No inconsistencies detected.")
            for r in risk["reasons"]:
                line("warn", "⚠️", r)

        st.markdown("### 🔗 Cross-document checks")
        if len(docs) < 2:
            st.info("Upload two or more documents to compare names, policy numbers, addresses and dates of birth.")
        elif not cross:
            st.info("The documents have no fields in common to compare.")
        for c in cross:
            cls, ic = {"match": ("ok", "✅"), "warn": ("warn", "⚠️"), "mismatch": ("flag", "🚩")}[c["status"]]
            line(cls, ic, f'<b>{c["field"]}</b>: {c["a"]} &nbsp;vs&nbsp; {c["b"]} <i>({c["detail"]})</i><br><small>{c["pair"]}</small>')

        st.markdown("### 📄 Per-document details")
        for d in docs:
            with st.expander(f"{d['name']}  ·  {d['data']['doc_type']}  ·  {'AI' if d['used_ai'] else 'offline'} extraction"):
                pk = d.get("packet")
                tabs = st.tabs((["📚 Packet map & citations"] if pk else []) +
                               ["Extracted data", "Policy DB & rulebook", "Checks", "Image forensics", "Raw text"])
                if pk:
                    tp, t1, t2, t3, t4, t5 = tabs
                    with tp:
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Pages analysed", pk["pages"])
                        m2.metric("Bill sections", len(pk["sections"]))
                        m3.metric("Findings (all cite pages)", len(pk["flags"]))
                        st.markdown("**Packet map**: what is on which pages")
                        stretch(st.dataframe, [{"Document type": t.replace("_", " ").title(), "Pages": cl.fmt_pages(range(a, b + 1)),
                                                "Count": b - a + 1} for t, a, b in pk["map"]], hide_index=True)
                        st.markdown("**Findings with page citations**")
                        if not pk["flags"]:
                            line("ok", "✅", "No inconsistencies found across the packet.")
                        for f in pk["flags"]:
                            line("flag" if f["sev"] == "high" else "warn", "🚩" if f["sev"] == "high" else "⚠️", f["msg"])
                        with st.expander("Per-page extracted facts"):
                            rows = [{"Page": n, "Type": pk["types"][n], "Name": f.get("patient_name"), "Policy": f.get("policy_number"),
                                     "DOB": f.get("dob"), "Items": len(f.get("items_detail") or []), "Total": f.get("stated_total")}
                                    for n, f in sorted(pk["facts"].items())
                                    if f.get("patient_name") or f.get("policy_number") or f.get("dob") or f.get("items_detail")
                                    or f.get("stated_total") is not None]
                            stretch(st.dataframe, rows, hide_index=True)
                else:
                    t1, t2, t3, t4, t5 = tabs
                with t1:
                    st.json({k: v for k, v in d["data"].items() if k not in ("red_flags", "line_items")})
                with t2:
                    rec = d["db"]["record"]
                    if rec:
                        st.markdown("**Policy record on file**")
                        st.json({k: rec[k] for k in ("policy_id", "holder_name", "plan_tier", "sum_insured", "start_date",
                                                     "expiry_date", "status")})
                    for v in d["db"]["verified"]:
                        line("ok", "✅", v)
                    for f in d["db"]["flags"] + d["kb"]["flags"]:
                        line("flag" if f["sev"] == "high" else "warn", "🚩" if f["sev"] == "high" else "⚠️", f["msg"])
                    for n in d["kb"]["notes"]:
                        st.info(n)
                    if not (d["db"]["verified"] or d["db"]["flags"] or d["kb"]["flags"]):
                        st.info("No policy number on this document, so there was nothing to look up.")
                    seen, shown = set(), []
                    for q in d["kb"]["queries"]:
                        for p in kb.retrieve(q, 1):
                            if p[1][:60] not in seen:
                                seen.add(p[1][:60])
                                shown.append(p)
                    if shown:
                        st.markdown("**Relevant rulebook passages**")
                        show_passages(shown)
                    if d["data"]["items_detail"] and st.button("🤖 Ask AI to review this bill against the rulebook", key=f"rev_{res['id']}_{d['name']}"):
                        if not client:
                            st.info("Add a GEMINI_API_KEY to enable the AI review. The rule checks above already ran offline.")
                        else:
                            items = "; ".join(f"{i['desc']} Rs {i['amount']:,.0f}" for i in d["data"]["items_detail"])
                            try:
                                ans, ps = kb.ask_rulebook(client, f"Under the {d['tier'] or 'unknown'} plan, which of these billed items "
                                                                  f"look excluded, overpriced or non-payable? {items}", d["tier"])
                                st.markdown(ans or "No answer.")
                                show_passages(ps)
                            except Exception as e:
                                st.warning(f"AI review unavailable ({type(e).__name__}).")
                with t3:
                    allf = [(f["sev"], f["msg"]) for f in d["flags"]] + list(d["meta"])
                    if not allf:
                        line("ok", "✅", "Nothing flagged")
                    for sev, msg in allf:
                        line("flag" if sev == "high" else "warn", "🚩" if sev == "high" else "⚠️", msg)
                with t4:
                    if not d["images"]:
                        st.info("No images found.")
                    for n_img, (orig, ela, info) in enumerate(d["images"], 1):
                        if info["suspicious"]:
                            line("flag", "🚩", f"<b>Image {n_img}:</b> {info['detail']}")
                        else:
                            line("ok", "✅", f"<b>Image {n_img}:</b> noise level is consistent across the image")
                        a, b = st.columns(2)
                        stretch(a.image, orig, caption="Original (suspicious area outlined in red)" if info["suspicious"] else "Original")
                        if ela:
                            stretch(b.image, ela, caption="Error Level Analysis (a visual hint: differences in compression history)")
                with t5:
                    st.text_area("Text", d["text"][:15000], height=250, key=f"txt_{res['id']}_{d['name']}")
                    if len(d["text"]) > 15000:
                        st.caption("Showing the first 15,000 characters. The full text was analysed.")

        st.markdown("### 📤 Export")
        rep = cl.build_report_dict(docs, cross, risk)
        e1, e2, e3 = st.columns(3)
        e1.download_button("⬇️ Executive summary (PDF)", cl.build_pdf(rep), "claimguard_summary.pdf", "application/pdf")
        e2.download_button("⬇️ Report (TXT)", cl.build_text(rep), "claimguard_report.txt")
        e3.download_button("⬇️ Data (JSON)", json.dumps(rep, indent=2, default=str), "claimguard_report.json")

# ====================================================================== TAB 2: FORM GUIDE
with tab_guide:
    st.markdown("### Pick what you are applying for")
    form = st.selectbox("Application type", list(cl.FORMS.keys()))
    info = cl.FORMS[form]
    res = st.session_state.get("analysis")
    corpus = ""
    if res:
        corpus = " ".join((d["text"] + " " + d["name"]).lower() for d in res["docs"])
        st.caption("Documents you uploaded in the Verify tab are auto-ticked when we recognise them. Tick the rest yourself.")

    st.markdown("#### ✅ Documents checklist")
    aid = st.session_state.get("aid", 0)
    have, missing = 0, []
    for i, (label, kws) in enumerate(info["docs"]):
        detected = any(k in corpus for k in kws) if corpus else False
        if st.checkbox(label, value=detected, key=f"chk_{form}_{i}_{aid}"):
            have += 1
        else:
            missing.append(label)
    pct = have / len(info["docs"])
    st.progress(pct, text=f"Packet readiness: {have}/{len(info['docs'])} documents ({pct:.0%})")
    if pct == 1:
        st.success("Packet looks complete. Run it through the Verify tab to catch inconsistencies before submitting.")
    elif missing:
        st.warning("Still missing: " + "; ".join(missing))

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("#### ✍️ How to fill the form")
        for t in info["fill"]:
            line("ok", "", t)
    with g2:
        st.markdown("#### ❌ Common reasons for rejection")
        for t in info["mistakes"]:
            line("flag", "", t)

    st.markdown("#### 🏆 Maximise your approval chances")
    for t in cl.APPROVAL_TIPS:
        st.markdown(f'<div class="glass" style="padding:.6rem 1rem;margin-bottom:.5rem">{t}</div>', unsafe_allow_html=True)

    st.markdown("#### 🤖 Personalised suggestions")
    if st.button("Get AI suggestions for my packet"):
        if not client:
            st.info("Add a GEMINI_API_KEY to enable personalised AI advice. The checklist and tips above work without it.")
        else:
            ents = [d["data"] for d in res["docs"]] if res else []
            try:
                with st.spinner("Thinking..."):
                    st.markdown(cl.ai_form_advice(client, form, ents, missing))
            except Exception as e:
                st.warning(f"AI advice unavailable ({type(e).__name__}). The checklist and tips above still apply.")
    st.caption("General guidance only. Requirements differ between insurers and banks, so confirm the exact list with yours. "
               "Following these tips improves your chances but cannot guarantee approval.")

# ====================================================================== TAB 3: POLICY DATABASE
with tab_db:
    st.markdown("### 🗄️ Mock policy database (SQLite)")
    st.caption("Demo records stored in `policies.db`. Uploaded bills are checked against this: does the policy exist, does the name match, "
               "is it active and past its waiting period, and does the claim fit the remaining cover.")

    with st.expander("➕ Add or update a policy (use an existing Policy ID to update it)"):
        with st.form("add_policy"):
            a1, a2 = st.columns(2)
            pid = a1.text_input("Policy ID", "HLT-2026-09999")
            holder = a2.text_input("Holder name")
            dep = a1.text_input("Dependants (comma separated)")
            dob = a2.date_input("Date of birth", value=None, min_value=date(1900, 1, 1), max_value=date.today())
            addr = st.text_input("Address")
            b1, b2, b3, b4 = st.columns(4)
            tier = b1.selectbox("Plan tier", ["Basic", "Silver", "Gold", "Platinum"], index=2)
            si = b2.number_input("Sum insured (Rs)", min_value=0, value=500000, step=50000)
            wait = b3.number_input("Waiting days", min_value=0, value=30)
            status = b4.selectbox("Status", ["active", "suspended", "lapsed"])
            d1, d2 = st.columns(2)
            start = d1.date_input("Start date", value=date.today(), min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
            end = d2.date_input("Expiry date", value=date.today() + timedelta(days=364), min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
            if st.form_submit_button("Save policy"):
                if pid.strip() and holder.strip():
                    pdb.add_policy({"policy_id": pid.strip(), "holder_name": holder.strip(), "dependants": dep, "dob": str(dob or ""),
                                    "address": addr, "plan_tier": tier, "sum_insured": si, "start_date": str(start),
                                    "expiry_date": str(end), "waiting_days": wait, "status": status})
                    st.success(f"Saved policy {pid.strip()}.")
                else:
                    st.error("Policy ID and holder name are required.")

    with st.expander("💳 Record a paid claim (used for remaining-cover and duplicate-claim checks)"):
        with st.form("add_claim"):
            ids = [p["policy_id"] for p in pdb.all_policies()]
            cpid = st.selectbox("Policy", ids)
            c1_, c2_, c3_ = st.columns(3)
            cdate = c1_.date_input("Claim date", value=date.today(), min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
            chosp = c2_.text_input("Hospital")
            camt = c3_.number_input("Amount (Rs)", min_value=0, value=10000, step=1000)
            if st.form_submit_button("Save claim"):
                pdb.add_claim(cpid, str(cdate), chosp.strip(), camt)
                st.success("Claim recorded.")

    with st.expander("🗑️ Delete a policy"):
        del_id = st.selectbox("Policy to delete", [p["policy_id"] for p in pdb.all_policies()], key="del_id")
        if st.button("Delete this policy and its claims"):
            pdb.delete_policy(del_id)
            st.success(f"Deleted {del_id}.")

    st.markdown("**Policies**")
    stretch(st.dataframe, pdb.all_policies(), hide_index=True)
    st.markdown("**Claims already paid**")
    stretch(st.dataframe, pdb.all_claims(), hide_index=True)

# ====================================================================== TAB 4: RULEBOOK (RAG)
with tab_kb:
    st.markdown("### 📚 Rulebook knowledge base")
    st.caption("Plan terms, exclusions and price benchmarks live in the `knowledge_base/` folder. Upload your own rulebooks (PDF, TXT, MD) "
               "and they are searched automatically. The demo numbers are illustrative: replace them with a real insurer's tariff sheet.")
    up = st.file_uploader("Add rulebook files", type=["pdf", "txt", "md"], accept_multiple_files=True, key="kbup")
    if up and st.button("Add to knowledge base"):
        for f in up:
            (kb.KB_DIR / Path(f.name).name).write_bytes(f.getvalue())
        st.success(f"Added {len(up)} file(s).")
    st.markdown("**Files in the knowledge base**")
    for name, n in kb.files_in_kb():
        st.markdown(f"- `{name}`" + (f" ({n} passages)" if n else " (used for structured price / exclusion checks)"))

    st.markdown("#### 💬 Ask the rulebook")
    q = st.text_input("Question", placeholder="e.g. Is dental treatment covered under the Silver plan?")
    tier_q = st.selectbox("Plan tier (optional)", ["", "Basic", "Silver", "Gold", "Platinum"])
    if q and st.button("Search rulebook"):
        try:
            ans, ps = kb.ask_rulebook(client, q, tier_q or None)
        except Exception as e:
            ans, ps = None, kb.retrieve(f"{q} {tier_q}", 4)
            st.warning(f"AI answer unavailable ({type(e).__name__}); showing the matching passages only.")
        if ans:
            st.markdown(ans)
        elif client is None:
            st.info("Showing the best-matching passages. Add a GEMINI_API_KEY to get a written answer grounded in them.")
        st.markdown("**Sources**")
        if ps:
            show_passages(ps)
        else:
            st.info("Nothing relevant found in the knowledge base.")
