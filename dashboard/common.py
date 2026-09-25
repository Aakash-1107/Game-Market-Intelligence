"""Shared look-and-feel for every page: category colours, plain-English labels,
the glossary sidebar, the "how to read / what this means" chart frame, and the
event-shading chart pattern (sale periods shaded behind a player-activity line)."""
import altair as alt
import pandas as pd
import streamlit as st

from db import query

# ---------------------------------------------------------------------------
# Colours. One meaning per colour, identical on every page.
# Validated (dataviz validate_palette.js, light surface, all pairs):
# aqua / blue / orange / violet and aqua / blue / orange / dark-orange pass CVD + normal-vision floors.
# Aqua sits at 2.7:1 contrast on white, so aqua marks always carry a label or tooltip.
# ---------------------------------------------------------------------------
UP = "#1baf7a"         # growing / surge / stayed higher
FLAT = "#2a78d6"       # stable / holds steady / back to normal
DOWN = "#eb6834"       # declining / slow fade / drop
DOWN_FAST = "#9c3a0e"  # big launch, fast drop
VOLATILE = "#4a3aa7"   # swings without a clear direction
NO_DATA = "#b5b3ab"    # not enough history / no effect
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SALE_WASH = "#eda100"  # sale periods: a translucent wash behind the line, never a data mark
STEAM_WIDE = "Steam-wide (3+ games at once)"

HEALTH = {  # an_activity_health.health_class -> (label, colour)
    "growing": ("Growing", UP),
    "stable": ("Stable", FLAT),
    "declining": ("Declining", DOWN),
    "volatile": ("Up-and-down", VOLATILE),
    "too_recent": ("Too new to judge", NO_DATA),
    "insufficient_history": ("Too new to judge", NO_DATA),
    "no_monthly_data": ("Too new to judge", NO_DATA),
}
HEALTH_ORDER = ["Growing", "Stable", "Up-and-down", "Declining", "Too new to judge"]

PATTERN = {  # an_game_lifecycle.lifecycle_pattern -> (label, colour)
    "growing": ("Keeps growing", UP),
    "sustained": ("Holds steady", FLAT),
    "gradual_decline": ("Slow fade", DOWN),
    "front_loaded": ("Big launch, fast drop", DOWN_FAST),
    "insufficient_history": ("Too new to tell", NO_DATA),
}
PATTERN_ORDER = ["Keeps growing", "Holds steady", "Slow fade", "Big launch, fast drop", "Too new to tell"]

OUTCOME = {  # an_sale_effect.sale_outcome -> (label, colour)
    "elevated_after": ("Stayed higher after the sale", UP),
    "returned_to_baseline": ("Went back to normal", FLAT),
    "below_baseline_after": ("Fell below normal", DOWN),
    "no_lift": ("No bump during the sale", NO_DATA),
}
OUTCOME_ORDER = [v[0] for v in OUTCOME.values()]


def scale_for(mapping: dict, order: list[str]) -> alt.Scale:
    colours = {label: colour for label, colour in mapping.values()}
    return alt.Scale(domain=order, range=[colours[label] for label in order])


GLOSSARY = """
**Players online** — how many people were playing the game at the same moment.
Monthly figures are the average of those readings over the month.

**Launch peak** — the busiest month in the first four months after the game came out on Steam.

**Typical level** — the game's usual player count around that time (median of the surrounding two months).
Used so a huge game and a small one can share one chart.

**Steam sale** — a period when the game was discounted on the Steam store.

**Unusual day** — a day far outside the game's normal range over the previous four weeks
(by pure chance you'd expect a day like that only about once a year).

**Early Access** — a game sold while still unfinished. Its "1.0 release" is the official finished version,
which Steam sometimes records as the release date.

**Free-to-play** — no purchase price, so no sales. The game earns money in other ways (in-game purchases).

**DLC** — paid add-on content for a game that's already out.
"""


PROJECT_TITLE = "Game Market Intelligence & Player Activity"
LOCAL_TZ = "Europe/Berlin"


def page_header(title: str, intro: str, period: str | None = None, project_title: bool = False) -> None:
    """period: one line saying which dates the page's data covers, shown right under the title."""
    if project_title:
        st.title(PROJECT_TITLE)
        st.subheader(title)
    else:
        st.title(title)
    if period:
        st.caption(f":material/calendar_month: **Data covered:** {period}")
    st.markdown(intro)
    with st.sidebar.expander("Glossary: terms used here", expanded=False):
        st.markdown(GLOSSARY)


def coverage() -> pd.Series:
    """Date range of each player-activity source, plus the longest hole in the live hourly feed."""
    return query("""
        with hours as (
            select distinct date_trunc('hour', recorded_at) as h
            from fact_player_activity where data_resolution = 'hourly'
        ),
        holes as (
            select lag(h) over (order by h) as gap_start, h as gap_end from hours
        ),
        biggest as (
            select gap_start, gap_end from holes
            where gap_end - gap_start > interval 3 hour
            order by gap_end - gap_start desc limit 1
        )
        select
            (select min(activity_month) from fact_player_activity_monthly)                        as monthly_first,
            (select max(activity_month) from fact_player_activity_monthly)                        as monthly_last,
            (select min(recorded_at) from fact_player_activity where data_resolution = '5min')    as fine_first,
            (select max(recorded_at) from fact_player_activity where data_resolution = '5min')    as fine_last,
            (select min(recorded_at) from fact_player_activity where data_resolution = 'hourly')  as live_first,
            (select max(recorded_at) from fact_player_activity where data_resolution = 'hourly')  as live_last,
            (select gap_start from biggest)                                                       as live_gap_start,
            (select gap_end from biggest)                                                         as live_gap_end
    """).iloc[0]


def local(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(LOCAL_TZ)


def live_snapshot() -> pd.DataFrame:
    """Per game from the live hourly feed: latest reading, 24-hour peak, 7-day average, and how the 7-day
    average compares with the last complete month (the latest month in fact_player_activity_monthly)."""
    return query("""
        with hourly as (
            select steam_app_id, player_count, recorded_at
            from fact_player_activity
            where data_resolution = 'hourly' and player_count is not null
        ),
        last_reading as (select max(recorded_at) as t from hourly),
        per_game as (
            select h.steam_app_id,
                   arg_max(h.player_count, h.recorded_at)                                  as now_players,
                   max(h.recorded_at)                                                      as now_at,
                   max(h.player_count) filter (where h.recorded_at > l.t - interval 24 hour) as peak_24h,
                   avg(h.player_count) filter (where h.recorded_at > l.t - interval 7 day)   as avg_7d
            from hourly h cross join last_reading l
            group by h.steam_app_id
        ),
        last_month as (
            select steam_app_id, activity_month as last_month, avg_players as last_month_avg
            from fact_player_activity_monthly
            where activity_month = (select max(activity_month) from fact_player_activity_monthly)
        )
        select g.steam_app_id, g.name, p.now_players, p.now_at, p.peak_24h, p.avg_7d,
               m.last_month, m.last_month_avg,
               p.avg_7d / nullif(m.last_month_avg, 0) - 1 as vs_last_month
        from dim_game g
        join per_game p using (steam_app_id)
        left join last_month m using (steam_app_id)
        order by g.name
    """)


def chart_block(title: str, how: str, chart, meaning: str) -> None:
    """Every chart ships with a finding-title, a 'how to read' line and a 'what this means' line."""
    st.markdown(f"#### {title}")
    st.caption(f"**How to read this:** {how}")
    st.altair_chart(style(chart), width="stretch", theme=None)
    st.markdown(f"**What this means:** {meaning}")
    st.write("")


def style(chart):
    return (
        chart.configure(font="system-ui, -apple-system, 'Segoe UI', sans-serif", background="transparent")
        .configure_view(stroke=None)
        .configure_axis(gridColor=GRID, domainColor="#c3c2b7", tickColor="#c3c2b7",
                        labelColor=INK_2, titleColor=INK_2, labelFontSize=12, titleFontSize=12,
                        titleFontWeight="normal")
        .configure_legend(labelColor=INK_2, titleColor=INK_2, labelFontSize=12, titleFontSize=12,
                          orient="top", titleFontWeight="normal", labelLimit=0)
    )


COUNT_AXIS = alt.Axis(format="d", tickMinStep=1)


def spread_labels(ends: pd.DataFrame, ycol: str, min_gap: float) -> pd.DataFrame:
    """Nudge line-end labels apart vertically so none overlap (adds column 'label_y')."""
    out = ends.sort_values(ycol).copy()
    ys = out[ycol].tolist()
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    out["label_y"] = ys
    return out


def pct(x: float, signed: bool = False) -> str:
    return f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%"


def game_image(url: str | None, width: int = 230) -> None:
    if url:
        st.image(url, width=width)


# ---------------------------------------------------------------------------
# Daily activity from the 5-minute backfill (21 games, Dec 2017 - Aug 2020),
# indexed to the game's own typical level so games of any size share an axis.
# ---------------------------------------------------------------------------
def daily_activity(steam_app_id: int) -> pd.DataFrame:
    df = query(
        """
        with d as (
            select cast(recorded_at as date) as day, avg(player_count) as players, count(*) as readings
            from fact_player_activity
            where steam_app_id = ? and data_resolution = '5min'
            group by 1
        )
        select day, players,
               players / median(players) over (
                   order by day rows between 30 preceding and 30 following) as vs_typical
        from d
        where readings >= 230   -- same >=80%-of-288 completeness rule the models use
        order by day
        """,
        (steam_app_id,),
    )
    df["day"] = pd.to_datetime(df["day"])
    # 7-day centred average removes the weekday/weekend rhythm so multi-day effects (sales) stand out
    df["vs_typical_7d"] = df["vs_typical"].rolling(7, center=True, min_periods=4).mean()
    return df


def event_chart(daily: pd.DataFrame, sales: pd.DataFrame, anomalies: pd.DataFrame | None = None,
                height: int = 300, smooth: bool = False):
    """Player activity (as % of typical level) with Steam sale periods shaded behind it.
    Optional anomaly markers: surges (up triangle), drops (down triangle), Steam-wide (grey).
    smooth=True plots the 7-day average; keep it off when marking single days."""
    ycol = "vs_typical_7d" if smooth else "vs_typical"
    x_dom = [daily["day"].min(), daily["day"].max()]
    x = alt.X("day:T", title=None, scale=alt.Scale(domain=x_dom), axis=alt.Axis(format="%b %Y"))

    layers = []
    if not sales.empty:
        s = sales.copy()
        s["sale_start"] = pd.to_datetime(s["sale_start"])
        s["sale_end_x"] = pd.to_datetime(s["sale_end"]) + pd.Timedelta(days=1)
        s = s[(s["sale_end_x"] >= x_dom[0]) & (s["sale_start"] <= x_dom[1])]
        s["legend"] = "Steam sale"
        layers.append(
            alt.Chart(s).mark_rect(opacity=0.28).encode(
                x=alt.X("sale_start:T", scale=alt.Scale(domain=x_dom)), x2="sale_end_x:T",
                color=alt.Color("legend:N", title=None, scale=alt.Scale(domain=["Steam sale"], range=[SALE_WASH])),
                tooltip=[alt.Tooltip("sale_start:T", title="Sale started", format="%d %b %Y"),
                         alt.Tooltip("sale_end:T", title="Sale ended", format="%d %b %Y"),
                         alt.Tooltip("max_discount_pct:Q", title="Discount %")],
            )
        )

    layers.append(alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=MUTED, strokeWidth=1).encode(y="y:Q"))
    layers.append(
        alt.Chart(daily).mark_line(color=FLAT, strokeWidth=1.6).encode(
            x=x,
            y=alt.Y(f"{ycol}:Q", title="Players vs. typical level", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("day:T", title="Day", format="%a %d %b %Y"),
                     alt.Tooltip(f"{ycol}:Q", title="vs. typical level" + (" (7-day average)" if smooth else ""),
                                 format=".0%"),
                     alt.Tooltip("players:Q", title="Players online (daily average)", format=",.0f")],
        )
    )

    if anomalies is not None and not anomalies.empty:
        a = anomalies.merge(daily[["day", "vs_typical", "players"]], left_on="activity_date", right_on="day")
        a["kind"] = a.apply(lambda r: STEAM_WIDE if r["is_market_wide"]
                            else ("Unusual surge" if r["direction"] == "spike" else "Unusual drop"), axis=1)
        kinds = ["Unusual surge", "Unusual drop", STEAM_WIDE]
        layers.append(
            alt.Chart(a).mark_point(filled=True, size=110, opacity=1, stroke="white", strokeWidth=1.5).encode(
                x="day:T", y="vs_typical:Q",
                shape=alt.Shape("kind:N", title=None, scale=alt.Scale(domain=kinds, range=["triangle-up", "triangle-down", "circle"])),
                fill=alt.Fill("kind:N", title=None, scale=alt.Scale(domain=kinds, range=[UP, DOWN, MUTED])),
                tooltip=[alt.Tooltip("day:T", title="Day", format="%a %d %b %Y"),
                         alt.Tooltip("kind:N", title="What happened"),
                         alt.Tooltip("vs_typical:Q", title="vs. typical level", format=".0%"),
                         alt.Tooltip("sale_discount_pct:Q", title="Sale discount % (if any)")],
            )
        )

    return alt.layer(*layers).resolve_scale(color="independent").properties(height=height)
