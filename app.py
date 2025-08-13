import io
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from fpdf import FPDF
import requests

st.set_page_config(page_title="MEA Shipment Checklist (PDF)", layout="wide")

# -------------------- Font setup (Unicode-safe) --------------------
FONTS_DIR = Path(__file__).parent / "fonts"
FONTS_DIR.mkdir(exist_ok=True)
TTF_PATH = FONTS_DIR / "DejaVuSans.ttf"

DEJAVU_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans.ttf"
FALLBACK_URL = "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"  # broad Latin coverage

def ensure_ttf() -> Path:
    if TTF_PATH.exists() and TTF_PATH.stat().st_size > 100000:
        return TTF_PATH
    url_list = [DEJAVU_URL, FALLBACK_URL]
    for url in url_list:
        try:
            r = requests.get(url, timeout=20)
            if r.ok and len(r.content) > 100000:
                TTF_PATH.write_bytes(r.content)
                return TTF_PATH
        except Exception:
            pass
    # As a last resort, write a tiny marker file so app still runs; PDF may fail for complex chars
    if not TTF_PATH.exists():
        TTF_PATH.write_bytes(b"")
    return TTF_PATH

# -------------------- Data --------------------

MIDDLE_EAST = [
    "Bahrain","Cyprus","Iran","Iraq","Israel","Jordan","Kuwait","Lebanon","Oman",
    "Palestine","Qatar","Saudi Arabia","Syria","Turkey","United Arab Emirates","Yemen","Egypt"
]
AFRICA = [
    "Algeria","Angola","Benin","Botswana","Burkina Faso","Burundi","Cabo Verde","Cameroon",
    "Central African Republic","Chad","Comoros","Congo (Republic)","Congo (DRC)","Djibouti",
    "Equatorial Guinea","Eritrea","Eswatini","Ethiopia","Gabon","Gambia","Ghana","Guinea",
    "Guinea-Bissau","Côte d’Ivoire","Kenya","Lesotho","Liberia","Libya","Madagascar",
    "Malawi","Mali","Mauritania","Mauritius","Morocco","Mozambique","Namibia","Niger",
    "Nigeria","Rwanda","Sao Tome and Principe","Senegal","Seychelles","Sierra Leone","Somalia",
    "South Africa","South Sudan","Sudan","Tanzania","Togo","Tunisia","Uganda","Zambia","Zimbabwe"
]
ALL_COUNTRIES = sorted(list(set(MIDDLE_EAST) | set(AFRICA)))

INCOTERMS = ["EXW","FCA","FOB","CFR","CIF","CPT","CIP","DAP","DPU","DDP"]
MODES = ["Air","Sea","Courier"]
COMMODITIES = ["General Electronics","Batteries (DG)","Chemicals (DG)","Telecom/Radio","Other"]

LEGALIZATION_NEEDED = set(["Jordan","Lebanon","Iraq","Palestine","Syria","Yemen","Libya","Tunisia","Algeria","Egypt","Morocco"])
SANCTIONS_COUNTRIES = set(["Iran","Syria","Libya","Sudan","South Sudan"])

BASELINE_DOCS = [
    ("Commercial Invoice","Yes","Shipper","Any","Any","Any","Signed & stamped; English unless required otherwise."),
    ("Packing List","Yes","Shipper","Any","Any","Any","Itemized with qty, net/gross weight, dimensions."),
    ("Certificate of Origin (COO)","Yes","Shipper","Any","Any","Any","Chamber of Commerce stamped; legalization may be requested."),
    ("HS Codes Confirmed","Yes","Shipper","Any","Any","Any","Ensure correct 8–10 digit HS per line item."),
    ("Product Description & Model/PN","Yes","Shipper","Any","Any","Any","Must match invoice & PL exactly."),
    ("Export Declaration (origin)","Yes","Shipper","Any","Any","Any","EX1/SAD or origin equivalent."),
    ("Transport Document","Yes","Shipper","Air","Any","Any","AWB for Air/Courier."),
    ("Transport Document","Yes","Shipper","Sea","Any","Any","Original B/L or telex release for Sea."),
    ("Transport Document","Yes","Shipper","Courier","Any","Any","Courier waybill/label."),
    ("Insurance Certificate","Conditional","Shipper","Any","Any","CIF/CIP or when risk transfers pre-delivery.","Provide if terms require seller insurance."),
    ("Dangerous Goods Declaration","Conditional","Shipper","Air","Batteries (DG)","Any","IATA DGD for DG shipments."),
    ("IMDG/Sea DG Declaration","Conditional","Shipper","Sea","Batteries (DG)","Any","IMDG declaration for sea DG."),
    ("MSDS/SDS","Conditional","Shipper","Any","Batteries (DG)","Any","Safety Data Sheet for batteries/chemicals."),
    ("Radio/Telecom Type Approval","Conditional","Importer","Any","Telecom/Radio","Any","Importer may need local approval for RF/telecom."),
]

COUNTRY_SPECIFIC = {c: [] for c in ALL_COUNTRIES}
for c in ["Bahrain","Kuwait","Oman","Qatar","Saudi Arabia","United Arab Emirates"]:
    COUNTRY_SPECIFIC[c] += [
        ("Commercial Invoice (Attested)","Yes","Shipper","Any","Any","Any","Chamber of Commerce attestation commonly requested."),
        ("COO (Legalized)","Conditional","Shipper","Any","Any","Any","Legalize via embassy/consulate if requested by importer."),
    ]
COUNTRY_SPECIFIC["Saudi Arabia"] += [("SABER/SALEEM CoC (regulated goods)","Conditional","Importer","Any","Any","Any","Conformity & shipment certification via SABER.")]
COUNTRY_SPECIFIC["Qatar"] += [("Product Compliance Pre-Approval (regulated)","Conditional","Importer","Any","Telecom/Radio","Any","Required for some electronics/telecom.")]
COUNTRY_SPECIFIC["Kuwait"] += [("KUCAS/PAI Conformity (regulated)","Conditional","Importer","Any","Any","Any","Public Authority for Industry compliance.")]
COUNTRY_SPECIFIC["Oman"] += [("Import Permit (DG/chemicals)","Conditional","Importer","Any","Batteries (DG)","Any","Check ROP/DGSM based on commodity.")]
for c in ["Jordan","Lebanon","Iraq","Palestine","Syria","Yemen"]:
    COUNTRY_SPECIFIC[c] += [("Invoice & COO Legalization","Conditional","Shipper","Any","Any","Any","Embassy legalization often required.")]
COUNTRY_SPECIFIC["Israel"] += [("SII Approval (regulated electronics)","Conditional","Importer","Any","Telecom/Radio","Any","Israel Standards Institute approvals.")]
COUNTRY_SPECIFIC["Turkey"] += [
    ("ATR or EUR.1 (if applicable)","Conditional","Shipper","Any","Any","Any","Preferential origin doc for Customs Union/EU origin."),
    ("Import License (telecom/RF, if applicable)","Conditional","Importer","Any","Telecom/Radio","Any","Permit for radio/telecom equipment when required."),
]
COUNTRY_SPECIFIC["Egypt"] += [
    ("ACID Number","Yes","Importer","Any","Any","Any","Advance Cargo Information Declaration (Nafeza)."),
    ("Invoice & COO Legalized","Conditional","Shipper","Any","Any","Any","Arabic details often required; legalize via embassy."),
]
COUNTRY_SPECIFIC["Morocco"] += [
    ("VoC/Conformity (regulated)","Conditional","Importer","Any","Any","Any","Verification of Conformity where applicable."),
    ("Arabic/French Invoice Copy","Conditional","Shipper","Any","Any","Any","Language preference for customs clarity."),
]
COUNTRY_SPECIFIC["Tunisia"] += [("Arabic/French Invoice Copy","Conditional","Shipper","Any","Any","Any","Language preference; legalization may be requested.")]
COUNTRY_SPECIFIC["Algeria"] += [("Arabic/French Invoice Copy","Conditional","Shipper","Any","Any","Any","Language preference; bank domiciliation may be requested.")]
COUNTRY_SPECIFIC["Libya"] += [("Legalized Documents","Conditional","Shipper","Any","Any","Any","Embassy legalization commonly required.")]
for c in ["Kenya","Tanzania","Uganda","Rwanda","Burundi"]:
    COUNTRY_SPECIFIC[c] += [("PVoC Certificate (regulated)","Conditional","Importer","Any","Any","Any","Pre-Export Verification of Conformity.")]
COUNTRY_SPECIFIC["Kenya"] += [("IDF (Import Declaration Form)","Yes","Importer","Any","Any","Any","Importer obtains; include on docs.")]
for c in ["Tanzania","Uganda"]:
    COUNTRY_SPECIFIC[c] += [("Import Permit (batteries/chemicals)","Conditional","Importer","Any","Batteries (DG)","Any","Check local authority for hazardous goods.")]
COUNTRY_SPECIFIC["Nigeria"] += [
    ("Form M","Yes","Importer","Any","Any","Any","Initiated by importer; must match invoice HS."),
    ("SONCAP (regulated)","Conditional","Importer","Any","Any","Any","Standards Org. of Nigeria Conformity Assessment."),
    ("PAAR","Yes","Importer","Any","Any","Any","Pre-Arrival Assessment Report (Customs)."),
]
COUNTRY_SPECIFIC["Ghana"] += [("G-CAP/CoC (regulated)","Conditional","Importer","Any","Any","Any","Conformity programme for selected goods.")]
COUNTRY_SPECIFIC["Ethiopia"] += [("ECAE CoC (regulated)","Conditional","Importer","Any","Any","Any","Conformity for selected goods.")]
COUNTRY_SPECIFIC["South Africa"] += [
    ("NRCS LOA/SABS (regulated)","Conditional","Importer","Any","Any","Any","Letters of Authority/Approvals for certain categories."),
    ("Import Permit (batteries/chemicals)","Conditional","Importer","Any","Batteries (DG)","Any","Regulator permits for hazardous goods."),
]
COUNTRY_SPECIFIC["Zimbabwe"] += [("CBCA Certificate (regulated)","Conditional","Importer","Any","Any","Any","Consignment Based Conformity Assessment.")]
COUNTRY_SPECIFIC["Zambia"] += [("ZABS CoC (regulated)","Conditional","Importer","Any","Any","Any","Bureau of Standards conformity for selected goods.")]
for c in ["Botswana","Lesotho","Namibia","Eswatini"]:
    COUNTRY_SPECIFIC[c] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Permits for selected goods (SACU).")]
for c in ["Senegal","Côte d’Ivoire","Mali","Burkina Faso","Niger","Guinea","Guinea-Bissau","Togo","Benin"]:
    COUNTRY_SPECIFIC[c] += [("VoC/CoC (regulated)","Conditional","Importer","Any","Any","Any","Verification/Certificate of Conformity via appointed agencies. ")]
for c in ["Cameroon","Gabon","Congo (Republic)","Congo (DRC)","Chad","Central African Republic","Equatorial Guinea"]:
    COUNTRY_SPECIFIC[c] += [("VoC/CoC (regulated)","Conditional","Importer","Any","Any","Any","Pre-shipment conformity assessment common.")]
for c in ["Somalia","Sudan","South Sudan","Eritrea","Djibouti"]:
    COUNTRY_SPECIFIC[c] += [("Legalized Invoice & COO","Conditional","Shipper","Any","Any","Any","Embassy/consulate legalization often required.")]
COUNTRY_SPECIFIC["Mauritius"] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Permits for regulated electronics/telecom as required.")]
COUNTRY_SPECIFIC["Seychelles"] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Permits for hazardous or regulated goods. ")]
COUNTRY_SPECIFIC["Cabo Verde"] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Importer secures permit where required.")]
COUNTRY_SPECIFIC["Sao Tome and Principe"] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Importer secures permit where required.")]
COUNTRY_SPECIFIC["Comoros"] += [("Import Permit (regulated)","Conditional","Importer","Any","Any","Any","Importer secures permit where required.")]

def master_dataframe():
    rows = []
    cols = ["Country","Document","Mandatory","Responsibility","Mode","Commodity","Incoterms","Notes","Legalization","Risk Flag"]
    for country in ALL_COUNTRIES:
        for (doc, mandatory, resp, mode, commodity, incoterm, notes) in BASELINE_DOCS:
            rows.append([country, doc, mandatory, resp, mode, commodity, incoterm, notes,
                         "Likely" if country in LEGALIZATION_NEEDED else "As requested",
                         "Sanctions/Export-Control Screen" if country in SANCTIONS_COUNTRIES else "None"])
        for (doc, mandatory, resp, mode, commodity, incoterm, notes) in COUNTRY_SPECIFIC.get(country, []):
            rows.append([country, doc, mandatory, resp, mode, commodity, incoterm, notes,
                         "Likely" if country in LEGALIZATION_NEEDED else "As requested",
                         "Sanctions/Export-Control Screen" if country in SANCTIONS_COUNTRIES else "None"])
    return pd.DataFrame(rows, columns=cols)

def filter_rows(df, country, incoterm, mode, commodity):
    m_country = df["Country"] == country
    m_mode = (df["Mode"] == "Any") | (df["Mode"] == mode)
    m_comm = (df["Commodity"] == "Any") | (df["Commodity"] == commodity)
    m_inc = (df["Incoterms"] == "Any") | (df["Incoterms"] == incoterm)
    return df[m_country & m_mode & m_comm & m_inc].reset_index(drop=True)

# -------------------- Sidebar --------------------
st.sidebar.title("Filters")
country = st.sidebar.selectbox("Destination Country", ALL_COUNTRIES, index=ALL_COUNTRIES.index("United Arab Emirates") if "United Arab Emirates" in ALL_COUNTRIES else 0)
incoterm = st.sidebar.selectbox("Incoterms", INCOTERMS, index=INCOTERMS.index("DAP"))
mode = st.sidebar.selectbox("Mode", MODES, index=0)
commodity = st.sidebar.selectbox("Commodity", COMMODITIES, index=0)

st.sidebar.markdown("---")
shipper = st.sidebar.text_input("Shipper (optional)")
consignee = st.sidebar.text_input("Consignee (optional)")
po = st.sidebar.text_input("PO/Reference (optional)")

# -------------------- Build the checklist --------------------
df_master = master_dataframe()
df_sel = filter_rows(df_master, country, incoterm, mode, commodity)

# Working view for editing
work_df = df_sel[["Document","Mandatory","Responsibility","Notes","Legalization","Risk Flag"]].copy()
work_df.insert(3, "Provided?", False)

st.title("MEA Shipment Checklist")
st.caption("Generate a customer-facing checklist as a **PDF** (no Excel needed).")

c1, c2, c3 = st.columns([2,2,3])
with c1:
    st.metric("Country", country)
with c2:
    st.metric("Incoterms", incoterm)
with c3:
    st.metric("Mode / Commodity", f"{mode} / {commodity}")

st.write("### Review & update")
edited = st.data_editor(
    work_df,
    use_container_width=True,
    num_rows="dynamic",
    hide_index=True,
    column_config={
        "Document": st.column_config.TextColumn(width="large"),
        "Mandatory": st.column_config.SelectboxColumn(options=["Yes","Conditional"]),
        "Responsibility": st.column_config.SelectboxColumn(options=["Shipper","Importer","Shared"]),
        "Provided?": st.column_config.CheckboxColumn(),
        "Notes": st.column_config.TextColumn(width="large"),
        "Legalization": st.column_config.SelectboxColumn(options=["Likely","As requested"]),
        "Risk Flag": st.column_config.SelectboxColumn(options=["None","Sanctions/Export-Control Screen"]),
    },
    key="editor",
)

# Status calculation
mandatory_mask = edited["Mandatory"] == "Yes"
mandatory_total = int(mandatory_mask.sum())
provided_yes = int(((edited["Provided?"] == True) & mandatory_mask).sum())
status = "READY ✅" if (mandatory_total > 0 and provided_yes == mandatory_total) else ("No mandatory docs" if mandatory_total == 0 else f"PENDING ⏳ ({provided_yes}/{mandatory_total})")

st.info(f"**Ready to Ship?** {status}")

# -------------------- PDF Generation --------------------
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ttf = ensure_ttf()
        # Register Unicode font
        if ttf.exists() and ttf.stat().st_size > 0:
            self.add_font("DejaVu", "", str(ttf), uni=True)
            self.set_font("DejaVu", size=10)
        else:
            # Fallback to core font; limited charset
            self.set_font("Helvetica", size=10)

    def header(self):
        self.set_font(self.font_family, "B", 12)
        self.cell(0, 10, "MEA Shipment Checklist", ln=1, align="C")
        self.set_font(self.font_family, "", 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, "This document is a practical guide. Verify country-specific requirements with your broker/forwarder.", ln=1, align="C")
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.font_family, "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

def _row_height(pdf, cells):
    max_lines = 1
    for text, w in cells:
        # rough estimate for Unicode font
        chars_per_line = int(w / 2.4)
        lines = max(1, (len(str(text)) // max(chars_per_line,1)) + 1)
        if lines > max_lines:
            max_lines = lines
    return max_lines * 5

def build_pdf(dataframe: pd.DataFrame, meta: dict) -> bytes:
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font_size(10)

    # Meta block
    pdf.set_font(style="B")
    pdf.cell(28, 6, "Country:"); pdf.set_font(style=""); pdf.cell(62, 6, meta["country"])
    pdf.set_font(style="B"); pdf.cell(26, 6, "Incoterms:"); pdf.set_font(style=""); pdf.cell(20, 6, meta["incoterm"])
    pdf.ln(6)
    pdf.set_font(style="B")
    pdf.cell(28, 6, "Mode:"); pdf.set_font(style=""); pdf.cell(62, 6, meta["mode"])
    pdf.set_font(style="B"); pdf.cell(26, 6, "Commodity:"); pdf.set_font(style=""); pdf.cell(20, 6, meta["commodity"])
    pdf.ln(6)
    if meta.get("shipper") or meta.get("consignee") or meta.get("po"):
        pdf.set_font(style="B"); pdf.cell(28, 6, "Shipper:"); pdf.set_font(style=""); pdf.cell(62, 6, meta.get("shipper",""))
        pdf.set_font(style="B"); pdf.cell(26, 6, "Consignee:"); pdf.set_font(style=""); pdf.cell(60, 6, meta.get("consignee",""))
        pdf.ln(6)
        if meta.get("po"):
            pdf.set_font(style="B"); pdf.cell(28,6,"PO/Ref:"); pdf.set_font(style=""); pdf.cell(62,6, meta.get("po",""))
            pdf.ln(6)
    pdf.ln(2)

    # Table header
    headers = [("Provided",16), ("Document",82), ("Mandatory",20), ("Resp.",20), ("Legal.",20), ("Risk",20)]
    pdf.set_fill_color(240,240,240)
    pdf.set_font(style="B")
    for text, w in headers:
        pdf.cell(w, 8, text, border=1, ln=0, align="C", fill=True)
    pdf.ln(8)
    pdf.set_font(style="")

    # Table rows
    for _, row in dataframe.iterrows():
        provided = "Yes" if bool(row.get("Provided?", False)) else "No"
        cells = [
            (provided, 16),
            (str(row["Document"]), 82),
            (row["Mandatory"], 20),
            (row["Responsibility"], 20),
            (row["Legalization"], 20),
            (row["Risk Flag"], 20),
        ]
        h = _row_height(pdf, cells)
        for (text, w) in cells:
            x = pdf.get_x(); y = pdf.get_y()
            pdf.multi_cell(w, 5, str(text), border=1, align="L")
            pdf.set_xy(x + w, y)
        pdf.ln(max(h, 5))

        note = str(row.get("Notes", "") or "").strip()
        if note:
            pdf.set_font(style="I")
            pdf.cell(16, 6, "", border="L")
            pdf.multi_cell(162, 6, "Notes: " + note, border="R")
            pdf.set_font(style="")
            pdf.cell(16, 0, "", border="L")
            pdf.cell(162, 0, "", border="R")
            pdf.ln(2)

    # Summary/status
    pdf.ln(2)
    pdf.set_font(style="B")
    pdf.cell(0, 6, f"Status: {meta['status']}", ln=1)
    pdf.set_font(style="")
    pdf.cell(0, 6, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=1)

    # Return bytes
    return bytes(pdf.output(dest="S"), encoding="latin-1", errors="ignore")  # safe for Streamlit download

# -------------------- Actions --------------------
meta = {
    "country": country,
    "incoterm": incoterm,
    "mode": mode,
    "commodity": commodity,
    "shipper": shipper,
    "consignee": consignee,
    "po": po,
    "status": status,
}

colA, colB = st.columns([1,2])
with colA:
    generate = st.button("📄 Generate PDF", type="primary")
with colB:
    st.caption("Tip: toggle **Provided?** for all mandatory docs to reach READY.")

if generate:
    pdf_bytes = build_pdf(edited, meta)
    filename = f"Shipment_Checklist_{country}_{incoterm}_{mode}_{datetime.now().strftime('%Y%m%d')}.pdf".replace(" ", "_")
    st.download_button("⬇️ Download PDF", data=pdf_bytes, file_name=filename, mime="application/pdf")
    st.success("PDF generated.")

st.markdown('---')
st.caption("Disclaimer: Requirements can change. Confirm with your customs broker/forwarder for the latest rules per HS code.")
