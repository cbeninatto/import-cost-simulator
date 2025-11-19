import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO


st.set_page_config(page_title="TIPI → CSV Extractor", page_icon="📑")

st.title("📑 TIPI → CSV Extractor")
st.markdown(
    """
Upload the official **TIPI PDF** and this app will generate a **tipi.csv** file with:

- `NCM` (only codes in the format `0000.00.00`)
- `Descricao`
- `Aliquota` (e.g. `0`, `10`, `NT`)

> ⚠️ TIPI is a very large PDF.  
> For performance reasons, we **limit how many pages are scanned**.  
> You can adjust the limit below if needed.
"""
)

uploaded_file = st.file_uploader("Select the TIPI PDF", type=["pdf"])

max_pages = st.number_input(
    "Max pages to scan (starting from page 1)",
    min_value=1,
    max_value=500,
    value=60,
    step=10,
    help=(
        "TIPI is huge. Parsing ALL pages can crash the app. "
        "60 pages is a good balance between coverage and performance. "
        "Increase carefully if you really need more."
    ),
)


def extract_tipi_from_pdf(pdf_bytes: bytes, max_pages: int) -> pd.DataFrame:
    """
    Extract rows from the TIPI PDF where NCM is in 0000.00.00 format,
    capturing DESCRIPTION (which may span multiple lines) and ALIQUOTA.

    We also stop after `max_pages` pages to avoid timeouts on very large PDFs.
    """

    # 1) NCM + description + aliquota on the same line
    #    e.g. "2204.30.00 Outros mostos de uvas 10"
    ncm_full = re.compile(r"^(\d{4}\.\d{2}\.\d{2})\s+(.+?)\s+(NT|\d+)\s*$")

    # 2) NCM at the start of the line, but maybe without aliquota yet
    ncm_only = re.compile(r"^(\d{4}\.\d{2}\.\d{2})\b")

    rows = []
    current = None  # pending block when description continues to next lines

    def normalize_description(parts):
        desc = " ".join(parts)
        desc = re.sub(r"\s+", " ", desc).strip(" -")
        return desc

    def finalize_current(cur):
        return {
            "NCM": cur["ncm"],
            "Descricao": normalize_description(cur["desc_parts"]),
            "Aliquota": cur["aliquota"],
        }

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
        last_page_index = min(max_pages, total_pages)  # 1-based pages: 1..last_page_index

        for page_index in range(last_page_index):
            page = pdf.pages[page_index]
            text = page.extract_text()
            if not text:
                continue

            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                stripped = line.strip()
                if not stripped:
                    continue

                # 1) Full match on a single line
                m_full = ncm_full.match(stripped)
                if m_full:
                    if current and current.get("aliquota"):
                        rows.append(finalize_current(current))
                    current = None

                    ncm, desc, aliquota = m_full.groups()
                    rows.append(
                        {
                            "NCM": ncm,
                            "Descricao": normalize_description([desc]),
                            "Aliquota": aliquota,
                        }
                    )
                    continue

                # 2) Line starts with NCM but no aliquota (multi-line description case)
                m_ncm = ncm_only.match(stripped)
                if m_ncm:
                    if current and current.get("aliquota"):
                        rows.append(finalize_current(current))

                    ncm = m_ncm.group(1)
                    rest = stripped[m_ncm.end():].strip()
                    current = {
                        "ncm": ncm,
                        "desc_parts": [rest] if rest else [],
                        "aliquota": None,
                    }
                    continue

                # 3) Continuation of an existing NCM block
                if current:
                    tokens = stripped.split()
                    if not tokens:
                        continue

                    last = tokens[-1]

                    # If the last token looks like an aliquota (e.g. 0, 10, NT)
                    if re.fullmatch(r"(NT|\d+)", last):
                        aliquota = last
                        desc_extra = " ".join(tokens[:-1])
                        if desc_extra:
                            current["desc_parts"].append(desc_extra)

                        current["aliquota"] = aliquota
                        rows.append(finalize_current(current))
                        current = None
                    else:
                        # Just more description text
                        current["desc_parts"].append(stripped)

    # End of PDF (or page limit): finalize block if it has an aliquota
    if current and current.get("aliquota"):
        rows.append(finalize_current(current))

    # Remove duplicates (same NCM, description, aliquota)
    unique = {(r["NCM"], r["Descricao"], r["Aliquota"]): r for r in rows}
    rows = list(unique.values())

    # Sort by NCM
    rows.sort(key=lambda r: r["NCM"])

    df = pd.DataFrame(rows, columns=["NCM", "Descricao", "Aliquota"])
    return df


if uploaded_file is not None:
    pdf_bytes = uploaded_file.read()

    with st.spinner("🔎 Extracting TIPI data..."):
        try:
            df = extract_tipi_from_pdf(pdf_bytes, max_pages=int(max_pages))
        except Exception as e:
            st.error(f"Error while processing PDF: {e}")
        else:
            if df.empty:
                st.warning(
                    "No rows found with NCM in the format 0000.00.00.\n"
                    "Check if the PDF is the official TIPI and if the layout matches the expected structure.\n\n"
                    "You can also try increasing the 'Max pages to scan' value."
                )
            else:
                st.success(
                    f"✅ Extraction finished — {len(df)} rows "
                    f"({df['NCM'].nunique()} unique NCM codes) "
                    f"from the first {int(max_pages)} page(s)."
                )

                # Show last few NCMs so you know where the scan stopped
                st.caption("Last 10 NCMs found in this run:")
                st.dataframe(df.tail(10))

                st.subheader("Preview (first 100 rows)")
                st.dataframe(df.head(100))

                csv_bytes = df.to_csv(index=False).encode("utf-8-sig")

                st.download_button(
                    "⬇️ Download tipi.csv",
                    data=csv_bytes,
                    file_name="tipi.csv",
                    mime="text/csv",
                )
else:
    st.info("Upload the TIPI PDF to start the extraction.")
