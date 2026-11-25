import base64
import io
from pathlib import Path

import streamlit as st
from PIL import Image

ASSETS = Path(__file__).parent / "assets"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}  # AVIF / HEIC are not supported: convert them to jpg

# ---- EDIT THESE ----
TEAM = ["Swayamshu Mohapatra", "Vishweshwar Kumbar", "Ankit Kodlyal", "Vivek Angadi N M ", "Tejoram Benki"]
TEAM_SUBTITLE = "RVCE · 1st Year"
TICKER = "OCR  •  Policy Database Lookup  •  Rulebook RAG  •  Error Level Analysis  •  Cross-Document Checks  •  Risk Scoring  •  "

_ACC = ["#00e5ff", "#a855f7", "#ff2fd2"]  # set per theme by render_landing()


def _t(s: str) -> str:
    """Recolour hard-coded accent colours to the active theme."""
    return s.replace("#00e5ff", _ACC[0]).replace("#a855f7", _ACC[1]).replace("#ff2fd2", _ACC[2])


def _clean(html: str) -> str:
    return "\n".join(l.strip() for l in html.splitlines() if l.strip())


def _md(html: str):
    st.markdown(_t(_clean(html)), unsafe_allow_html=True)


# ---------------------------------------------------------------- images (never blank, never broken)
@st.cache_data(show_spinner=False)
def _photo_uri(path: str, mtime: float) -> str | None:
    try:
        img = Image.open(path)
        img = img.convert("RGB")  # also takes the first frame of GIFs
        img.thumbnail((720, 720))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None  # unreadable file: skipped instead of showing a broken-image icon


def _user_images():
    """[(stem, data_uri)] for every readable image in ./assets."""
    out = []
    if ASSETS.exists():
        for p in sorted(ASSETS.iterdir()):
            if p.suffix.lower() in IMG_EXT:
                uri = _photo_uri(str(p), p.stat().st_mtime)
                if uri:
                    out.append((p.stem, uri))
    return out


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(_t(svg).encode()).decode()


def art_svg(kind: str) -> str:
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><defs>'
            '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1d1a55"/><stop offset="1" stop-color="#0c0a2b"/></linearGradient>'
            '<linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#00e5ff"/><stop offset="1" stop-color="#ff2fd2"/></linearGradient>'
            '<radialGradient id="glow"><stop offset="0" stop-color="#a855f7" stop-opacity=".6"/><stop offset="1" stop-color="#a855f7" stop-opacity="0"/></radialGradient>'
            '</defs><rect width="400" height="400" fill="url(#bg)"/>'
            '<style>.fl{animation:fl 4s ease-in-out infinite}@keyframes fl{50%{transform:translateY(-14px)}}'
            '.pu{transform-box:fill-box;transform-origin:center;animation:pu 3s ease-in-out infinite}@keyframes pu{50%{transform:scale(1.12);opacity:.7}}'
            '.dr{stroke-dasharray:220;stroke-dashoffset:220;animation:dr 3s ease-in-out infinite}@keyframes dr{50%,80%{stroke-dashoffset:0}100%{stroke-dashoffset:220}}'
            '.sp{animation:sp 9s linear infinite;transform-origin:200px 200px}@keyframes sp{to{transform:rotate(360deg)}}'
            '.sp2{animation:sp 14s linear infinite reverse;transform-origin:200px 200px}'
            '.sc{animation:sc 4s ease-in-out infinite}@keyframes sc{0%,100%{transform:translateX(-70px)}50%{transform:translateX(70px)}}'
            '.bar{transform-box:fill-box;transform-origin:bottom;animation:bar 2.6s ease-in-out infinite alternate}@keyframes bar{from{transform:scaleY(.35)}to{transform:scaleY(1)}}'
            '</style>')
    bodies = {
        "shield": '<circle cx="200" cy="200" r="180" fill="url(#glow)" class="pu"/>'
                  '<g class="fl"><path d="M200 60 L315 105 V215 C315 285 262 325 200 352 C138 325 85 285 85 215 V105 Z" fill="#1d1a55" stroke="url(#g)" stroke-width="8"/>'
                  '<path class="dr" d="M142 208 L188 254 L262 160" fill="none" stroke="#2ee59d" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/></g>',
        "magnifier": '<rect x="90" y="70" width="220" height="260" rx="14" fill="#262266" stroke="url(#g)" stroke-width="3"/>'
                     + "".join(f'<rect x="115" y="{100 + i * 30}" width="{150 - (i % 3) * 25}" height="9" rx="4" fill="#8f8bd8" opacity=".6"/>' for i in range(7))
                     + '<g class="sc"><circle cx="200" cy="200" r="62" fill="#a855f7" fill-opacity=".18" stroke="url(#g)" stroke-width="8"/>'
                       '<line x1="246" y1="246" x2="300" y2="300" stroke="url(#g)" stroke-width="14" stroke-linecap="round"/></g>',
        "orbit": '<circle cx="200" cy="200" r="150" fill="none" stroke="#8f8bd8" stroke-opacity=".3" stroke-dasharray="6 8"/>'
                 '<circle cx="200" cy="200" r="100" fill="none" stroke="#8f8bd8" stroke-opacity=".3" stroke-dasharray="6 8"/>'
                 '<circle cx="200" cy="200" r="34" fill="url(#g)" class="pu"/>'
                 '<g class="sp"><circle cx="200" cy="50" r="13" fill="#00e5ff"/><circle cx="200" cy="350" r="9" fill="#ff2fd2"/></g>'
                 '<g class="sp2"><circle cx="300" cy="200" r="11" fill="#a855f7"/><circle cx="100" cy="200" r="9" fill="#2ee59d"/></g>',
        "docs": "".join(f'<g class="fl" style="animation-delay:{i * .5}s"><rect x="{90 + i * 38}" y="{95 + i * 30}" width="150" height="190" rx="12" fill="#262266" '
                         f'stroke="url(#g)" stroke-width="3"/><rect x="{110 + i * 38}" y="{120 + i * 30}" width="90" height="9" rx="4" fill="#8f8bd8"/>'
                         f'<rect x="{110 + i * 38}" y="{145 + i * 30}" width="110" height="9" rx="4" fill="#8f8bd8" opacity=".6"/></g>' for i in range(3)),
        "lock": '<circle cx="200" cy="215" r="150" fill="url(#glow)" class="pu"/>'
                '<path d="M140 190 V145 C140 105 260 105 260 145 V190" fill="none" stroke="url(#g)" stroke-width="18" stroke-linecap="round"/>'
                '<rect x="110" y="185" width="180" height="140" rx="22" fill="#1d1a55" stroke="url(#g)" stroke-width="7"/>'
                '<circle cx="200" cy="245" r="17" fill="#2ee59d"/><rect x="193" y="250" width="14" height="38" rx="6" fill="#2ee59d"/>',
        "chart": "".join(f'<rect class="bar" x="{85 + i * 52}" y="{250 - h}" width="34" height="{h}" rx="8" fill="url(#g)" style="animation-delay:{i * .3}s"/>'
                         for i, h in enumerate([70, 120, 95, 170, 140, 200]))
                 + '<polyline class="dr" points="100,230 150,190 205,205 255,140 310,160 360,90" fill="none" stroke="#2ee59d" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
                 '<line x1="60" y1="330" x2="350" y2="330" stroke="#8f8bd8" stroke-opacity=".4" stroke-width="3"/>',
    }
    return head + bodies[kind] + "</svg>"


ART = [("shield", "Verified & protected"), ("magnifier", "Forensic inspection"), ("orbit", "The reasoning engine"),
       ("docs", "Documents, decoded"), ("lock", "Privacy first"), ("chart", "Risk, quantified")]


def _img(uri: str, alt: str = "") -> str:
    return f'<img src="{uri}" alt="{alt}" loading="eager"/>'


def _hero_visual() -> str:
    for stem, uri in _user_images():
        if "hero" in stem.lower():
            return _img(uri, "hero")
    return _img(_svg_uri(art_svg("shield")), "shield")


# ---------------------------------------------------------------- animated diagrams
def pipeline_svg() -> str:
    nodes = [("📤", "Upload"), ("🔤", "OCR"), ("🗄️", "Policy DB"), ("📚", "Rulebook"), ("✅", "Verdict")]
    xs = [90, 270, 450, 630, 810]
    parts = [f'<path class="flow" d="M{a + 44} 100 L{b - 44} 100"/>' for a, b in zip(xs, xs[1:])]
    for i, (x, (emo, label)) in enumerate(zip(xs, nodes)):
        parts.append(f'<circle class="node" cx="{x}" cy="100" r="40" style="animation-delay:{i * 0.4}s"/>')
        parts.append(f'<text x="{x}" y="112" font-size="34">{emo}</text>')
        parts.append(f'<text x="{x}" y="175" font-size="18">{label}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 210">
<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#00e5ff"/><stop offset="1" stop-color="#ff2fd2"/></linearGradient></defs>
<style>
.flow{{stroke:url(#g);stroke-width:3;stroke-dasharray:10 10;fill:none;animation:dash 1s linear infinite}}
@keyframes dash{{to{{stroke-dashoffset:-20}}}}
.node{{fill:#1b1850;stroke:url(#g);stroke-width:3;transform-box:fill-box;transform-origin:center;animation:pulse 2.4s ease-in-out infinite}}
@keyframes pulse{{50%{{transform:scale(1.14)}}}}
text{{font-family:Helvetica,Arial,sans-serif;fill:#e8e8ff;text-anchor:middle}}
</style>
{''.join(parts)}
<circle r="7" fill="#fff"><animateMotion dur="5s" repeatCount="indefinite" path="M90 100 L810 100"/></circle>
</svg>"""


def neural_svg() -> str:
    layers, xs, pos = [3, 5, 5, 2], [100, 300, 500, 700], []
    for x, n in zip(xs, layers):
        gap = 300 / (n + 1)
        pos.append([(x, gap * (j + 1)) for j in range(n)])
    lines, nodes, k = [], [], 0
    for L in range(len(pos) - 1):
        for (x1, y1) in pos[L]:
            for (x2, y2) in pos[L + 1]:
                lines.append(f'<line class="flow" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" style="animation-delay:{(k % 7) * 0.15}s"/>')
                k += 1
    for L, layer in enumerate(pos):
        for j, (x, y) in enumerate(layer):
            nodes.append(f'<circle class="n" cx="{x}" cy="{y}" r="13" style="animation-delay:{(L * 0.3 + j * 0.2):.1f}s"/>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300">
<style>
.flow{{stroke:#a855f7;stroke-opacity:.45;stroke-width:1.2;stroke-dasharray:6 6;animation:dash 1.2s linear infinite}}
@keyframes dash{{to{{stroke-dashoffset:-24}}}}
.n{{fill:#00e5ff;transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-in-out infinite}}
@keyframes pulse{{50%{{transform:scale(1.5);fill:#ff2fd2}}}}
</style>
{''.join(lines)}{''.join(nodes)}
</svg>"""


def _svg_img(svg: str) -> str:
    return f'<img src="{_svg_uri(svg)}" style="width:100%"/>'


# ---------------------------------------------------------------- CSS
CSS = """
<style>
.lp-hero{display:flex;flex-wrap:wrap;align-items:center;gap:2.5rem;padding:1.5rem 0 2.5rem}
.lp-hero-text{flex:1 1 380px}
.lp-hero-img{flex:1 1 320px;max-width:520px;animation:floaty 6s ease-in-out infinite}
.lp-hero-img img{width:100%;display:block;border-radius:26px;box-shadow:0 0 70px rgba(168,85,247,.6)}
.typing{font-size:1.9rem;font-weight:700;white-space:nowrap;overflow:hidden;max-width:100%;width:0;
border-right:3px solid #00e5ff;animation:typing 3.2s steps(37) .3s forwards,caret .8s step-end infinite}
@keyframes typing{to{width:37ch}}
@keyframes caret{50%{border-color:transparent}}
@keyframes floaty{50%{transform:translateY(-18px) rotate(1.2deg)}}
.lp-sub{font-size:1.1rem;opacity:.85;line-height:1.7;margin-top:1rem}
.ticker{overflow:hidden;white-space:nowrap;border-block:1px solid rgba(255,255,255,.18);padding:.7rem 0;margin:1rem 0 3rem;background:rgba(255,255,255,.04)}
.ticker span{display:inline-block;padding-left:100%;animation:tick 28s linear infinite;font-weight:600;letter-spacing:.05em}
@keyframes tick{to{transform:translateX(-100%)}}
.lp-h2{font-size:2.1rem;font-weight:700;margin:3rem 0 1rem;background:linear-gradient(90deg,#00e5ff,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.lp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1.2rem;margin:1rem 0}
.lp-card{background:rgba(255,255,255,.06);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.15);border-radius:18px;
padding:1.3rem;box-shadow:0 8px 32px rgba(0,0,0,.35);transition:.3s;text-align:center}
.lp-card:hover{transform:translateY(-8px);box-shadow:0 0 35px rgba(0,229,255,.45)}
.lp-title{margin:.4rem 0;font-size:1.15rem;font-weight:700;text-align:center}
.lp-card p{opacity:.8;margin:0;line-height:1.55}
.big{font-size:2.4rem;line-height:1.2;text-align:center}
.diagram{padding:1.2rem;border-radius:22px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12)}
.avatar{width:84px;height:84px;border-radius:50%;display:grid;place-items:center;font-size:1.6rem;font-weight:700;letter-spacing:.03em;position:relative;margin:0 auto 12px}
.avatar::before{content:"";position:absolute;inset:0;border-radius:50%;background:conic-gradient(#00e5ff,#a855f7,#ff2fd2,#00e5ff);animation:spin 5s linear infinite}
.avatar::after{content:"";position:absolute;inset:4px;border-radius:50%;background:#16143a}
.avatar span{position:relative;z-index:1}
@keyframes spin{to{transform:rotate(360deg)}}
.team{text-align:center}
.team-grid{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.pic{border-radius:22px;overflow:hidden;border:1px solid rgba(255,255,255,.18);box-shadow:0 10px 40px rgba(0,0,0,.4)}
.pic img{width:100%;display:block}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:1.5rem;padding-bottom:4rem}
.gal{position:relative;border-radius:22px;overflow:hidden;border:1px solid rgba(255,255,255,.18);aspect-ratio:1/1;background:#16143a}
.gal img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .6s}
.gal:hover img{transform:scale(1.08)}
.gal .cap{position:absolute;bottom:0;left:0;right:0;padding:.7rem 1rem;font-size:.9rem;background:linear-gradient(transparent,rgba(0,0,0,.8))}
.cta{text-align:center;margin:3rem 0 2rem;font-size:1.6rem;font-weight:700}
.cta .arrow{display:block;font-size:2.4rem;animation:bounce 1.2s ease-in-out infinite}
@keyframes bounce{50%{transform:translateY(14px)}}
@keyframes rev{from{opacity:0;transform:translateY(70px) scale(.95)}to{opacity:1;transform:none}}
@keyframes revL{from{opacity:0;transform:translateX(-120px)}to{opacity:1;transform:none}}
@keyframes revR{from{opacity:0;transform:translateX(120px)}to{opacity:1;transform:none}}
@keyframes zoomin{from{transform:scale(1.18)}to{transform:scale(1)}}
@keyframes drift1{from{transform:translateY(40px)}to{transform:translateY(-20px)}}
@keyframes drift2{from{transform:translateY(80px)}to{transform:translateY(-40px)}}
@supports (animation-timeline:view()){
.reveal{animation:rev linear both;animation-timeline:view();animation-range:entry 0% entry 90%}
.from-left{animation:revL linear both;animation-timeline:view();animation-range:entry 0% entry 90%}
.from-right{animation:revR linear both;animation-timeline:view();animation-range:entry 0% entry 90%}
.gal img{animation:zoomin linear both;animation-timeline:view();animation-range:entry 0% entry 100%}
.drift1{animation:drift1 linear both;animation-timeline:view()}
.drift2{animation:drift2 linear both;animation-timeline:view()}
}
</style>
"""


def render_landing(accents=None):
    global _ACC
    if accents:
        _ACC = list(accents)
    st.markdown(_t(_clean(CSS)), unsafe_allow_html=True)

    _md(f"""
    <div class="lp-hero">
      <div class="lp-hero-text">
        <div class="typing">Catch fraud before it costs millions.</div>
        <p class="lp-sub">ClaimGuard AI reads, inspects and cross-checks insurance documents in seconds, verifying them against a
        policy database and a rulebook, then giving one clear, explainable risk verdict.</p>
      </div>
      <div class="lp-hero-img">{_hero_visual()}</div>
    </div>
    <div class="ticker"><span>{TICKER * 3}</span></div>
    """)

    _md("""
    <div class="lp-h2 reveal">What it does</div>
    <div class="lp-grid">
      <div class="lp-card from-left"><div class="big">🔤</div><div class="lp-title">Smart OCR</div><p>Reads scanned bills, IDs and multi-page PDFs, even when there is no selectable text.</p></div>
      <div class="lp-card from-right"><div class="big">🗄️</div><div class="lp-title">Policy database lookup</div><p>Confirms the policy exists, the name matches, it is active, and the claim fits the remaining cover.</p></div>
      <div class="lp-card from-left"><div class="big">📚</div><div class="lp-title">Rulebook (RAG)</div><p>Retrieves the plan terms to flag overcharging and items the plan does not cover, with sources.</p></div>
      <div class="lp-card from-right"><div class="big">🔬</div><div class="lp-title">Image forensics</div><p>Error Level Analysis and PDF metadata checks reveal edited regions and editing software.</p></div>
    </div>
    """)

    _md(f"""
    <div class="lp-h2 reveal">How it works</div>
    <div class="diagram reveal">{_svg_img(pipeline_svg())}</div>
    """)

    _md(f"""
    <div class="lp-hero" style="padding-top:3rem">
      <div class="lp-hero-text from-left">
        <div class="lp-h2" style="margin-top:0">The AI engine</div>
        <p class="lp-sub">Extracted text and forensic signals flow through a language model and a rule engine that reason over
        the whole document packet, spotting mismatched names, impossible dates and totals that do not add up.</p>
      </div>
      <div class="diagram from-right" style="flex:1 1 380px">{_svg_img(neural_svg())}</div>
    </div>
    """)

    def _initials(name):
        w = name.split()
        return (w[0][0] + (w[-1][0] if len(w) > 1 else "")).upper()

    team_html = "".join(
        f'<div class="lp-card team reveal"><div class="avatar"><span>{_initials(n)}</span></div>'
        f'<div class="lp-title">{n}</div><p>{TEAM_SUBTITLE}</p></div>' for n in TEAM)
    _md(f"""
    <div class="lp-h2 reveal">About us</div>
    <div class="lp-hero" style="padding:0 0 1rem">
      <div class="lp-hero-text from-left">
        <p class="lp-sub" style="margin-top:0">We are a team of 1st-year RVCE students from interdisciplinary branches, working together to build tools that make document verification faster, fairer, and more transparent. Insurance and loan processing still depends on people comparing stacks of pages by hand. We believe AI should take over the tedious cross-checking and hand humans a clear, explainable summary to make the final call.</p>
      </div>
      <div class="pic from-right" style="flex:1 1 300px;max-width:420px">{_img(_svg_uri(art_svg("orbit")), "team")}</div>
    </div>
    <div class="lp-grid">
      <div class="lp-card from-left"><div class="big">🎯</div><div class="lp-title">Mission</div><p>Cut manual verification time while catching inconsistencies humans miss.</p></div>
      <div class="lp-card reveal"><div class="big">👁️</div><div class="lp-title">Vision</div><p>Trustworthy, explainable automation for every claim and loan package.</p></div>
      <div class="lp-card from-right"><div class="big">🔒</div><div class="lp-title">Privacy first</div><p>Uploads are processed in memory and are not stored.</p></div>
    </div>
    <div class="lp-h2 reveal">Meet the team</div>
    <div class="lp-grid team-grid">{team_html}</div>
    """)

    # GALLERY: every readable image in ./assets (except the hero), padded with animated artwork up to at least 6 tiles
    tiles = [(stem.replace("_", " ").replace("-", " ").title(), uri) for stem, uri in _user_images() if "hero" not in stem.lower()][:9]
    for kind, cap in ART:
        if len(tiles) >= 6:
            break
        tiles.append((cap, _svg_uri(art_svg(kind))))
    gal = "".join(
        f'<div class="gal {"drift1" if i % 2 == 0 else "drift2"}">{_img(uri, cap)}<div class="cap">{cap}</div></div>'
        for i, (cap, uri) in enumerate(tiles))
    _md(f"""
    <div class="lp-h2 reveal">Gallery</div>
    <div class="gallery">{gal}</div>
    <div class="cta reveal">Try it yourself<span class="arrow">⬇</span></div>
    """)
