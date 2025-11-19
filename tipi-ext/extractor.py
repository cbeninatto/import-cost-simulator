import os
from io import StringIO

import streamlit as st
import pandas as pd
from openai import OpenAI


# --- OpenAI client (reads key from Streamlit secrets or env) ---
def get_client() -> OpenAI:
    api_key = None

    # 1) Streamlit secrets (recommended on Streamlit Cloud)
    if "OPENAI_API_KEY" in st.secrets:
        api_key = st.secrets["OPENAI_API_KEY"]

    # 2) Fallback to environment variable, if set
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        st.error(
            "OPENAI_API_KEY not found. "
            "Set it in Streamlit secrets or as an environment variable."
        )
        st.stop()

    return OpenAI(api_key=api_key)


st.set_page_config(page_title="TIPI → CSV Extractor (OpenAI)", page_icon="📑")

st.title("📑 TIPI → CSV Extractor (using OpenAI)")
st.markdown(
    """
Upload the official **TIPI PDF** and this app will use **ChatGPT** to parse it and
return a **CSV** with:

- `NCM` (only codes in the format `0000.00.00`)
- `Descricao`
- `Aliquota` (numeric or `NT`, without `%`)

> The parsing is done by OpenAI (PDF file input), not by `pdfplumber`.
"""
)

uploaded_file = st.file_uploader("Select the TIPI PDF", type=["pdf"])

model_name = st.selectbox(
    "Model",
    options=["gpt-4.1-mini", "gpt-4.1", "gpt-4o"],
    index=0,
    help=(
        "gpt-4.1-mini: cheaper and usually enough for extraction.\n"
        "gpt-4.1 / gpt-4o: more capable, more expensive."
    ),
)


def build_extraction_prompt() -> str:
    """
    Instructions to ChatGPT for how to extract TIPI rows.
    """
    return """
You are a Brazilian tax table extraction assistant.

You are given the official TIPI PDF (Tabela de Incidência do Imposto sobre Produtos Industrializados).

Task:
- Read the TIPI table in the PDF.
- Extract ONLY the rows where the NCM code is exactly in the format `0000.00.00`
  (four digits, dot, two digits, dot, two digits).

For each such row, output one line in **CSV** with the columns:

NCM,Descricao,Aliquota

Definitions and rules:

1. NCM:
   - Keep it exactly as in the table, e.g. `2204.30.00`.
   - Only include codes in the format `0000.00.00`.

2. Descricao:
   - The full Portuguese description of that NCM line.
   - If the description is broken across multiple lines in the PDF,
     join them into a single line separated by spaces.
   - Remove line breaks and unnecessary extra spaces.

3. Aliquota:
   - The TIPI IPI rate for that NCM, as shown in the table.
   - Use only the numeric value (e.g. `0`, `5`, `10`) or the literal `NT`
     if it is "não tributado".
   - Do NOT include the percent sign `%`.

Output format (very important):
- Output **only** CSV, nothing else.
- First line must be the header exactly:
  `NCM,Descricao,Aliquota`
- Each subsequent line: one NCM row.
- Do not output explanations, comments, or any additional text.
- Do not repeat the prompt.
- Do not add extra columns.

Be exhaustive and careful: include all valid NCM rows in the PDF.
"""


def call_openai_for_csv(file_obj, filename: str, model: str) -> str:
    """
    Send the uploaded PDF to OpenAI and get back CSV text.
    """
    client = get_client()

    # 1) Upload the PDF to OpenAI's Files API
    uploaded = client.files.create(
        file=file_obj,  # this is a file-like object from Streamlit uploader
        purpose="user_data",
    )

    # 2) Ask the model to extract CSV
    prompt = build_extraction_prompt()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "file_id": uploaded.id,
                    },
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                ],
            }
        ],
        temperature=0,
    )

    # New Responses API has a convenience property:
    csv_text = response.output_text

    if not csv_text:
        raise RuntimeError("Model returned empty content.")

    return csv_text


if uploaded_file is not None:
    st.info(
        "When you click **Extract**, the PDF will be sent to OpenAI. "
        "The model will read the entire TIPI and return CSV."
    )

    if st.button("🚀 Extract TIPI → CSV using ChatGPT"):
        with st.spinner("Calling OpenAI to extract TIPI data... This may take a while."):
            try:
                # Important: Streamlit's UploadedFile is file-like, we can pass it directly.
                csv_text = call_openai_for_csv(
                    file_obj=uploaded_file, filename=uploaded_file.name, model=model_name
                )
            except Exception as e:
                st.error(f"Error calling OpenAI: {e}")
            else:
                # Try to parse the CSV text into a DataFrame
                try:
                    df = pd.read_csv(StringIO(csv_text))
                except Exception as e:
                    st.error(
                        "OpenAI returned something that could not be parsed as CSV. "
                        "Showing raw output below so you can inspect it."
                    )
                    st.code(csv_text[:5000], language="text")
                else:
                    st.success(
                        f"✅ Extraction finished — {len(df)} rows "
                        f"({df['NCM'].nunique()} unique NCM codes)."
                    )

                    st.subheader("Preview (first 100 rows)")
                    st.dataframe(df.head(100))

                    # Export as tipi.csv
                    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button(
                        "⬇️ Download tipi.csv",
                        data=csv_bytes,
                        file_name="tipi.csv",
                        mime="text/csv",
                    )
else:
    st.info("Upload the TIPI PDF to start.")
