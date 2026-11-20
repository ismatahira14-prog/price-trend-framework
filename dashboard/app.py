"""Single-page entry point for the IMIS inflation dashboard."""

import streamlit as st

st.set_page_config(
    page_title="Pakistan Inflation Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Hide Streamlit's framework chrome. The dashboard's own PBS banner is the
# first visible element; there is no page menu, Deploy button, or overflow
# menu above it.
st.markdown(
    """
    <style>
    :root {
        --imis-ink: #14231d;
        --imis-muted: #617068;
        --imis-green: #0b6e4f;
        --imis-green-dark: #07533c;
        --imis-line: #dfe8e3;
        --imis-surface: #ffffff;
        --imis-canvas: #f4f7f5;
    }
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stSidebar"],
    #MainMenu {
        display: none !important;
    }
    html body .stMainBlockContainer,
    html body [data-testid="stMainBlockContainer"],
    html body .block-container {
        padding: 0 .75rem 1.25rem .75rem !important;
        margin-top: 0 !important;
        width: 100% !important;
        max-width: none !important;
    }
    [data-testid="stAppViewContainer"], .stApp {
        background: var(--imis-canvas);
        color: var(--imis-ink);
    }
    html, body, [class*="st-"] {
        font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    h1, h2, h3, h4 {
        color: var(--imis-ink);
        letter-spacing: -0.025em;
    }
    h3 {
        margin-top: .95rem !important;
        margin-bottom: .35rem !important;
        padding-bottom: .38rem;
        border-bottom: 1px solid var(--imis-line);
    }
    [data-testid="stCaptionContainer"] {
        color: var(--imis-muted);
    }
    [data-baseweb="select"] > div {
        background: var(--imis-surface);
        border-color: #cbd9d2;
        border-radius: 10px;
        min-height: 38px;
        box-shadow: 0 1px 2px rgba(18, 45, 34, .04);
    }
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--imis-green);
        box-shadow: 0 0 0 3px rgba(11, 110, 79, .12);
    }
    .stButton > button, .stDownloadButton > button {
        border-radius: 9px;
        border-color: #c8d8d0;
        font-weight: 600;
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        color: var(--imis-green-dark);
        border-color: var(--imis-green);
        box-shadow: 0 4px 12px rgba(11, 110, 79, .12);
        transform: translateY(-1px);
    }
    [data-testid="stDataFrame"] {
        overflow: hidden;
        border: 1px solid var(--imis-line);
        border-radius: 12px;
        box-shadow: 0 4px 18px rgba(19, 49, 37, .055);
        background: var(--imis-surface);
    }
    iframe {
        border-radius: 12px;
    }
    [data-testid="stVerticalBlock"] {
        gap: .58rem;
    }
    [data-testid="stHorizontalBlock"] {
        gap: .8rem;
    }
    [data-testid="stDivider"] {
        margin: .8rem 0 !important;
    }
    [data-testid="stCaptionContainer"] p {
        margin-bottom: 0;
    }
    @media (max-width: 768px) {
        html body .stMainBlockContainer,
        html body [data-testid="stMainBlockContainer"],
        html body .block-container {
            padding: 0 .5rem 1rem .5rem !important;
        }
        h3 { font-size: 1.15rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

home = st.Page("pages/0_Home.py", title="Home", default=True)
medical_group = st.Page("pages/2_Medical_Group.py", title="Medical Groups")
# Nav stays hidden - each page renders its own in-theme st.page_link row.
st.navigation([home, medical_group], position="hidden").run()
