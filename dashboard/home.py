"""Entry point. Run from the project root:  streamlit run dashboard/home.py"""
import streamlit as st

st.set_page_config(page_title="PC Game Market Intelligence", page_icon=":material/sports_esports:", layout="wide")

pages = [
    st.Page("views/0_Overview.py", title="Market overview", icon=":material/home:", default=True),
    st.Page("views/1_Lifecycle.py", title="Life after launch", icon=":material/timeline:"),
    st.Page("views/2_Activity_Health.py", title="Activity health", icon=":material/monitor_heart:"),
    st.Page("views/3_Sale_Effect.py", title="Do sales bring players?", icon=":material/sell:"),
    st.Page("views/4_Market_Events.py", title="Unusual days", icon=":material/bolt:"),
    st.Page("views/5_Game_Explorer.py", title="Game explorer", icon=":material/search:"),
]
st.navigation(pages).run()
