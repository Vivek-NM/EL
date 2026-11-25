"""Mock policy database (SQLite) used to verify documents against 'real' policyholder records."""
import sqlite3
from contextlib import closing
from difflib import get_close_matches
from pathlib import Path

from fpdf import FPDF

import claimlogic as cl

DB = Path(__file__).parent / "policies.db"
BILLISH = ("medical_bill", "claim_form", "discharge_summary", "policy")

# policy_id, holder, dependants, dob, address, tier, sum_insured, start, expiry, waiting_days, status
SEED_POLICIES = [
    ("HLT-2026-00123", "Rahul Sharma", "Meera Sharma", "2001-03-12", "12 MG Road, Hyderabad", "Gold", 500000, "2026-04-01", "2027-03-31", 30, "active"),
    ("HLT-2025-00456", "Ananya Reddy", "", "1998-07-21", "45 Jubilee Hills, Hyderabad", "Silver", 300000, "2025-06-01", "2026-05-31", 30, "active"),
    ("HLT-2026-00789", "Mohammed Irfan Khan", "Sana Khan", "1990-11-02", "8 Banjara Hills, Hyderabad", "Platinum", 1000000, "2026-01-01", "2026-12-31", 30, "active"),
    ("HLT-2026-01001", "Priya Nair", "", "1995-01-30", "22 Gandhi Nagar, Bengaluru", "Basic", 200000, "2026-10-20", "2027-10-19", 30, "active"),
    ("HLT-2026-00555", "Suresh Kumar", "Lakshmi Kumar", "1982-05-09", "3 Anna Salai, Chennai", "Gold", 500000, "2026-02-01", "2027-01-31", 30, "active"),
    ("HLT-2026-00222", "Kavya Iyer", "", "2000-09-14", "17 Park Street, Kolkata", "Silver", 300000, "2026-03-01", "2027-02-28", 30, "active"),
    ("HLT-2026-00333", "Arjun Mehta", "Neha Mehta", "1987-12-25", "9 Marine Drive, Mumbai", "Basic", 200000, "2026-05-01", "2027-04-30", 30, "suspended"),
]
SEED_CLAIMS = [  # policy_id, claim_date, hospital, amount
    ("HLT-2026-00123", "2026-06-10", "Apollo Hospital", 20000),
    ("HLT-2026-00555", "2026-04-18", "Fortis Hospital", 250000),
    ("HLT-2026-00555", "2026-08-02", "MIOT Hospital", 170000),
]


def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def ensure_db():
    with closing(_conn()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS policies(
            policy_id TEXT PRIMARY KEY, holder_name TEXT, dependants TEXT, dob TEXT, address TEXT, plan_tier TEXT,
            sum_insured REAL, start_date TEXT, expiry_date TEXT, waiting_days INTEGER, status TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS claims(
            id INTEGER PRIMARY KEY AUTOINCREMENT, policy_id TEXT, claim_date TEXT, hospital TEXT, amount REAL)""")
        if c.execute("SELECT COUNT(*) FROM policies").fetchone()[0] == 0:
            c.executemany("INSERT INTO policies VALUES (?,?,?,?,?,?,?,?,?,?,?)", SEED_POLICIES)
            c.executemany("INSERT INTO claims(policy_id,claim_date,hospital,amount) VALUES (?,?,?,?)", SEED_CLAIMS)
        c.commit()


def all_policies():
    ensure_db()
    with closing(_conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM policies ORDER BY policy_id")]


def all_claims():
    ensure_db()
    with closing(_conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM claims ORDER BY policy_id, claim_date")]


def add_policy(rec):
    ensure_db()
    with closing(_conn()) as c:
        c.execute("INSERT OR REPLACE INTO policies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (rec["policy_id"], rec["holder_name"], rec.get("dependants", ""), rec.get("dob", ""), rec.get("address", ""),
                   rec["plan_tier"], rec["sum_insured"], rec["start_date"], rec["expiry_date"], rec.get("waiting_days", 30),
                   rec.get("status", "active")))
        c.commit()


def add_claim(policy_id, claim_date, hospital, amount):
    ensure_db()
    with closing(_conn()) as c:
        c.execute("INSERT INTO claims(policy_id,claim_date,hospital,amount) VALUES (?,?,?,?)",
                  (policy_id, claim_date, hospital, amount))
        c.commit()


def delete_policy(policy_id):
    ensure_db()
    with closing(_conn()) as c:
        c.execute("DELETE FROM claims WHERE policy_id=?", (policy_id,))
        c.execute("DELETE FROM policies WHERE policy_id=?", (policy_id,))
        c.commit()


def _flag(sev, msg):
    return {"sev": sev, "kind": "db", "msg": msg}


def verify_policy(data):
    """Check an extracted document against the policy database.
    Returns {'flags': [...], 'verified': [str], 'record': dict|None, 'claims': [...]}"""
    out = {"flags": [], "verified": [], "record": None, "claims": []}
    pid = data.get("policy_number")
    if not pid:
        if data.get("doc_type") in BILLISH:
            out["flags"].append(_flag("low", "No policy number on this document, so coverage cannot be verified"))
        return out

    rows = all_policies()
    rec = next((r for r in rows if cl._alnum(r["policy_id"]) == cl._alnum(pid)), None)
    if rec is None:
        ids = {cl._alnum(r["policy_id"]): r["policy_id"] for r in rows}
        close = get_close_matches(cl._alnum(pid), list(ids), n=1, cutoff=0.8)
        hint = f" Closest policy on file: {ids[close[0]]} (possible typo or altered number)." if close else ""
        out["flags"].append(_flag("high", f"Policy {pid} does NOT exist in the policy database.{hint}"))
        return out
    out["record"] = rec
    out["verified"].append(f"Policy {rec['policy_id']} found: {rec['holder_name']}, {rec['plan_tier']} plan, "
                           f"sum insured Rs {rec['sum_insured']:,.0f}")

    # holder / dependants name
    if data.get("patient_name"):
        names = [rec["holder_name"]] + [n.strip() for n in (rec["dependants"] or "").split(",") if n.strip()]
        best = max(cl.name_sim(data["patient_name"], n) for n in names)
        if best >= 0.97:
            out["verified"].append(f"Patient name matches the policy record ({best:.0%})")
        elif best >= 0.75:
            out["flags"].append(_flag("low", f"Patient name '{data['patient_name']}' only partly matches the policy record "
                                             f"('{rec['holder_name']}', {best:.0%})"))
        else:
            out["flags"].append(_flag("high", f"Patient name '{data['patient_name']}' is not the policy holder or a listed "
                                              f"dependant ('{rec['holder_name']}')"))
    if data.get("dob") and rec.get("dob"):
        a, b = cl.parse_date(data["dob"]), cl.parse_date(rec["dob"])
        if a and b and a != b:
            out["flags"].append(_flag("high", f"Date of birth {a} differs from the policy record ({b})"))

    # status + period
    if rec["status"] != "active":
        out["flags"].append(_flag("high", f"Policy status is '{rec['status']}', not active"))
    dd = data.get("dates") or {}
    treat = cl.parse_date(dd.get("admission")) or cl.parse_date(dd.get("bill_date")) or cl.parse_date(dd.get("claim_date"))
    start, end = cl.parse_date(rec["start_date"]), cl.parse_date(rec["expiry_date"])
    if treat and start and end:
        if treat > end:
            out["flags"].append(_flag("high", f"Treatment date {treat} is after the policy expired on {end}"))
        elif treat < start:
            out["flags"].append(_flag("high", f"Treatment date {treat} is before the policy started on {start}"))
        elif (treat - start).days < (rec["waiting_days"] or 0):
            out["flags"].append(_flag("high", f"Treatment is only {(treat - start).days} days after policy start, inside the "
                                              f"{rec['waiting_days']}-day initial waiting period (accidents excepted)"))
        else:
            out["verified"].append(f"Policy was active on the treatment date (valid until {end})")

    # cover + duplicates
    claims = [c for c in all_claims() if c["policy_id"] == rec["policy_id"]]
    out["claims"] = claims
    claimed = sum(c["amount"] for c in claims)
    total = data.get("stated_total") or (sum(data.get("line_items") or []) or None)
    if total:
        remaining = rec["sum_insured"] - claimed
        if total > remaining:
            out["flags"].append(_flag("high", f"Claim of Rs {total:,.0f} exceeds the remaining cover of Rs {remaining:,.0f} "
                                              f"(sum insured Rs {rec['sum_insured']:,.0f}, already claimed Rs {claimed:,.0f})"))
        else:
            out["verified"].append(f"Claim of Rs {total:,.0f} is within the remaining cover of Rs {remaining:,.0f}")
        for c in claims:
            same_amt = abs(c["amount"] - total) <= 1
            same_hosp = (not data.get("hospital")) or cl.name_sim(data["hospital"], c["hospital"]) >= 0.8
            if same_amt and same_hosp:
                out["flags"].append(_flag("high", f"Possible duplicate: an identical claim of Rs {c['amount']:,.0f} at "
                                                  f"{c['hospital']} is already on file ({c['claim_date']})"))
    return out


# ------------------------------------------------------------------
# Demo documents that match the seeded database
# ------------------------------------------------------------------
SAMPLES = {
    "genuine_bill.pdf": [
        "City Care Hospital", "FINAL BILL / TAX INVOICE", "Bill No: CC-88231",
        "Patient Name: Rahul Sharma", "Policy No: HLT-2026-00123", "Address: 12 MG Road, Hyderabad",
        "Policy Period: 01/04/2026 to 31/03/2027", "Date of Admission: 10/09/2026", "Date of Discharge: 13/09/2026",
        "Bill Date: 13/09/2026", "Hospital: City Care Hospital",
        "Appendectomy surgery   Rs. 85,000", "Room charges   Rs. 12,000", "Pharmacy   Rs. 6,500", "Total Rs. 103,500",
    ],
    "tampered_bill.pdf": [
        "City Care Hospital", "FINAL BILL / TAX INVOICE", "Bill No: CC-88231",
        "Patient Name: Rahul Sharma", "Policy No: HLT-2026-00132", "Address: 12 MG Road, Hyderabad",
        "Policy Period: 01/04/2026 to 31/03/2027", "Date of Admission: 14/09/2026", "Date of Discharge: 11/09/2026",
        "Bill Date: 11/09/2026", "Hospital: City Care Hospital",
        "Appendectomy surgery   Rs. 1,60,000", "Room charges   Rs. 12,000", "Pharmacy   Rs. 6,500",
        "Cosmetic procedure   Rs. 25,000", "Total Rs. 1,90,000",
    ],
    "id_card.pdf": [
        "Aadhaar Identity Card", "Name: Rahul Sharma", "DOB: 12/03/2001", "Address: 12 MG Road, Hyderabad",
    ],
    "id_card_mismatch.pdf": [
        "Aadhaar Identity Card", "Name: Rakesh Verma", "DOB: 12/03/2001", "Address: 45 Park Street, Kolkata",
    ],
}


def sample_pdf(name) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in SAMPLES[name]:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def sample_packet_pdf(tampered=True, pages=120) -> bytes:
    """A 100+ page claim packet. The tampered version hides inconsistencies deep inside the file:
    a different name on one page, a different policy number on another, a conflicting discharge date,
    an excluded procedure and a bill total that does not add up."""
    sp = {
        1: ["MEDICAL INSURANCE CLAIM FORM", "Patient Name: Rahul Sharma", "Policy No: HLT-2026-00123",
            "Policy Period: 01/04/2026 to 31/03/2027", "Hospital: City Care Hospital"],
        2: ["Aadhaar Identity Card", "Name: Rahul Sharma", "DOB: 12/03/2001", "Address: 12 MG Road, Hyderabad"],
        20: ["DISCHARGE SUMMARY", "Patient Name: Rahul Sharma", "Date of Admission: 10/09/2026",
             "Date of Discharge: 13/09/2026", "Hospital: City Care Hospital"],
        pages - 10: ["FINAL BILL / TAX INVOICE", "Bill No: CC-88231", "Patient Name: Rahul Sharma",
                     "Policy No: HLT-2026-00123", "Bill Date: 13/09/2026",
                     "Appendectomy surgery   Rs. 85,000", "Room charges   Rs. 12,000"],
        pages - 9: ["Pharmacy   Rs. 6,500",
                    "Cosmetic procedure   Rs. 25,000" if tampered else "Physiotherapy   Rs. 25,000",
                    "Total Rs. 1,20,000" if tampered else "Total Rs. 128,500"],
    }
    if tampered:
        sp[57] = ["LABORATORY REPORT", "Patient Name: Rakesh Verma", "Test: Haemoglobin    Result: normal"]
        sp[83] = ["Pharmacy Bill", "Patient Name: Rahul Sharma", "Policy No: HLT-2026-00132"]
        sp[90] = ["Nursing note", "Date of Discharge: 15/09/2026"]
    filler = ["Clinical observation record. Vitals stable and recorded at regular intervals.",
              "Patient comfortable. Medication administered as prescribed by the consultant.",
              "Dietary advice followed. Mobility assisted. No adverse reaction observed.",
              "Ward round completed. Nursing staff updated the care plan accordingly."]
    pdf = FPDF()
    pdf.set_auto_page_break(False)
    pdf.set_font("Helvetica", size=11)
    for n in range(1, pages + 1):
        pdf.add_page()
        lines = sp.get(n) or [f"Supporting record - sheet {n}"] + [filler[(n + i) % len(filler)] for i in range(22)]
        for ln in lines:
            pdf.cell(0, 8, ln, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
