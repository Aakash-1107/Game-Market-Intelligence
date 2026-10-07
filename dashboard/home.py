"""Entry point. Run from the project root:  streamlit run dashboard/home.py"""
import streamlit as st

from common import PROJECT_TITLE, sources_footer

st.set_page_config(page_title=PROJECT_TITLE, page_icon=":material/sports_esports:", layout="wide")
# Full menu (toolbarMode = "developer" in .streamlit/config.toml) without the Deploy button (deployment is done from
# the Community Cloud workspace, not from inside the app).
st.html("<style>[data-testid='stAppDeployButton'] { display: none; }</style>")

pages = [
    st.Page("views/0_Overview.py", title="Market overview", icon=":material/home:", default=True),
    st.Page("views/1_Lifecycle.py", title="Life after launch", icon=":material/timeline:"),
    st.Page("views/2_Activity_Health.py", title="Activity health", icon=":material/monitor_heart:"),
    st.Page("views/3_Sale_Effect.py", title="Do discounts bring players?", icon=":material/sell:"),
    st.Page("views/4_Market_Events.py", title="Unusual days", icon=":material/bolt:"),
    st.Page("views/5_Game_Explorer.py", title="Game explorer", icon=":material/search:"),
    st.Page("views/6_Data.py", title="How the data is built", icon=":material/database:"),
    st.Page("views/7_Pipeline_Health.py", title="Pipeline health", icon=":material/health_and_safety:"),
]
try:
    st.navigation(pages).run()
finally:   # also after a page called st.stop()
    sources_footer()
