"""Shared look-and-feel for every page: category colours, plain-English labels,
the glossary sidebar, the "how to read / what this means" chart frame, and the
event-shading chart pattern (sale periods shaded behind a player-activity line)."""
from pathlib import Path

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

HEALTH = {  # rpt_activity_health.health_class -> (label, colour)
    "growing": ("Growing", UP),
    "stable": ("Stable", FLAT),
    "declining": ("Declining", DOWN),
    "volatile": ("Up-and-down", VOLATILE),
    "too_recent": ("Too new to judge", NO_DATA),
    "insufficient_history": ("Too new to judge", NO_DATA),
    "no_monthly_data": ("Too new to judge", NO_DATA),
}
HEALTH_ORDER = ["Growing", "Stable", "Up-and-down", "Declining", "Too new to judge"]

PATTERN = {  # rpt_game_lifecycle.lifecycle_pattern -> (label, colour)
    "growing": ("Keeps growing", UP),
    "sustained": ("Holds steady", FLAT),
    "gradual_decline": ("Slow fade", DOWN),
    "front_loaded": ("Big launch, fast drop", DOWN_FAST),
    "insufficient_history": ("Too new to tell", NO_DATA),
}
PATTERN_ORDER = ["Keeps growing", "Holds steady", "Slow fade", "Big launch, fast drop", "Too new to tell"]

OUTCOME = {  # rpt_discount_effect.sale_outcome -> (label, colour)
    "elevated_after": ("Stayed higher after the discount", UP),
    "returned_to_baseline": ("Went back to normal", FLAT),
    "below_baseline_after": ("Fell below normal", DOWN),
    "no_lift": ("No bump during the discount", NO_DATA),
}
OUTCOME_ORDER = [v[0] for v in OUTCOME.values()]


def scale_for(mapping: dict, order: list[str]) -> alt.Scale:
    colours = {label: colour for label, colour in mapping.values()}
    return alt.Scale(domain=order, range=[colours[label] for label in order])


GLOSSARY = """
**Players online** — how many people were playing the game at the same moment.
Monthly figures are the average of those readings over the month.

**Launch peak** — the busiest month in the first four months after the game came out on Steam.

**Before-discount level** — the average daily players in the 14 days before a discount started. It is 100% on the
discount charts, so a huge game and a small one can share one chart.

**Previous 28 days** — the baseline for unusual days: the game's typical level over the 28 days before (on a log
scale), with an expected range of ±3 standard deviations around it.

**Days** — calendar days in UTC.

**Steam discount** — a period when the game was cheaper than its normal price on the Steam store.

**Unusual day** — a day far outside the game's normal range over the previous four weeks
(by pure chance you'd expect a day like that only about once a year).

**Early Access** — a game sold while still unfinished. Its "1.0 release" is the official finished version,
which Steam sometimes records as the release date.

**Free-to-play** — no purchase price, so no discounts. The game earns money in other ways (in-game purchases).

**DLC** — paid add-on content for a game that's already out.
"""


PROJECT_TITLE = "PC Game Market & Activity Intelligence"
LOCAL_TZ = "Europe/Berlin"
ASSETS = Path(__file__).resolve().parent / "assets"

# Valve brand rules: the logo stands alone (no words attached to it) and is never the most prominent element,
# so this attribution text is shown separately from the logo.
STEAM_ATTRIBUTION = ("Hourly player counts, player reviews and game details come from the Steam Web API. "
                     "Steam and the Steam logo are trademarks and/or registered trademarks of Valve Corporation "
                     "in the U.S. and/or other countries. This project is not affiliated with or endorsed by Valve.")


def glossary_sidebar() -> None:
    with st.sidebar.expander("Glossary: terms used here", expanded=False):
        st.markdown(GLOSSARY)


def page_header(title: str, intro: str, period: str | None = None) -> None:
    """period: one line saying which dates the page's data covers, shown right under the title."""
    st.title(title)
    if period:
        st.caption(f":material/calendar_month: **Data covered:** {period}")
    st.markdown(intro)
    glossary_sidebar()


# Official artwork, black version = Valve's logo for light backgrounds. The app theme is locked to light in
# .streamlit/config.toml, so no dark variant is needed. (Don't switch on st.context.theme.type: it follows the
# viewer's OS dark-mode preference even when the app itself is locked to light.)
STEAM_LOGO = ASSETS / "steam_logo_black.png"


def _logo_tooltip_css() -> str:
    """Hover text on the Steam logo, styled like Streamlit's own help tooltips (st.image has no `help`).
    Colours match the fixed light theme in .streamlit/config.toml. The text only appears on hover,
    so the logo itself still stands alone as Valve's brand rules require."""
    text = STEAM_ATTRIBUTION.replace('"', '\\"')
    return f"""<style>
    /* the logo is always the right-most item of the header row, so the tooltip opens leftwards on-screen.
       The non-wrapping header row gets overflow:auto from Streamlit, which would clip the tooltip; the title
       wraps instead of overflowing, so the row can safely show overflow. */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stLayoutWrapper"] > .st-key-steam_logo) {{ overflow: visible; }}
    .st-key-steam_logo {{ position: relative; overflow: visible; }}
    .st-key-steam_logo [data-testid="stElementToolbar"] {{ display: none; }}  /* no "fullscreen" button on a logo */
    .st-key-steam_logo::after {{
        content: "{text}";
        position: absolute; top: calc(100% + 6px); right: 0; z-index: 1000;
        width: min(340px, calc(100vw - 48px)); padding: 6px 12px; border-radius: 8px;
        background: #f7f6f2; color: rgb(49, 51, 63); box-shadow: rgba(0, 0, 0, 0.16) 0 1px 4px;
        font-size: 14px; line-height: 1.5; text-align: left; white-space: normal;
        opacity: 0; visibility: hidden; pointer-events: none;
        transition: opacity 0.15s ease 0.3s, visibility 0s linear 0.45s;
    }}
    .st-key-steam_logo:hover::after {{
        opacity: 1; visibility: visible; transition: opacity 0.15s ease 0.3s, visibility 0s;
    }}
    </style>"""


def project_header(subtitle: str) -> None:
    """Home-page header: project title left, Steam logo right, always on one row.
    wrap=False + a stretching title: on narrower screens (e.g. laptops at 125-150 % scaling) the title
    text breaks onto two lines instead of the logo dropping below the title."""
    with st.container(horizontal=True, wrap=False, vertical_alignment="center", gap="medium"):
        st.title(PROJECT_TITLE, width="stretch")
        if STEAM_LOGO.exists():
            with st.container(key="steam_logo", width="content"):
                st.image(str(STEAM_LOGO), width=170)
            st.html(_logo_tooltip_css())
    st.markdown(f":gray[{subtitle}]")
    glossary_sidebar()


def coverage() -> pd.Series:
    """Date range of each player-activity source, plus the longest hole in the live hourly feed."""
    return query("""
        with hours as (
            select distinct date_trunc('hour', recorded_at) as h
            from marts.fact_player_activity where data_resolution = 'hourly'
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
            (select min(activity_month) from marts.fact_player_activity_monthly)                  as monthly_first,
            (select max(activity_month) from marts.fact_player_activity_monthly)                  as monthly_last,
            -- 5-minute range from the daily table (the public snapshot has no 5-minute rows): UTC days as
            -- timestamptz at 00:00 UTC; pages show these as days or months, identical to the raw first/last reading
            (select timezone('UTC', min(activity_date)::timestamp) from marts.fact_player_activity_daily
             where data_resolution = '5min')                                                     as fine_first,
            (select timezone('UTC', max(activity_date)::timestamp) from marts.fact_player_activity_daily
             where data_resolution = '5min')                                                     as fine_last,
            (select min(recorded_at) from marts.fact_player_activity where data_resolution = 'hourly') as live_first,
            (select max(recorded_at) from marts.fact_player_activity where data_resolution = 'hourly') as live_last,
            (select gap_start from biggest)                                                       as live_gap_start,
            (select gap_end from biggest)                                                         as live_gap_end
    """).iloc[0]


def pipeline_counts() -> pd.Series:
    """Headline pipeline-scale numbers (home page genre headline + 'How the data is built')."""
    return query("""
        select
            (select count(*) from marts.dim_game)                                    as games,
            (select count(*) from marts.dim_game where is_free)                      as free_games,
            (select min(activity_month) from marts.fact_player_activity_monthly)     as first_month,
            -- hourly rows + 5-minute readings counted from the daily table (the public snapshot has no 5-minute rows)
            (select count(*) from marts.fact_player_activity where data_resolution <> '5min')
              + (select coalesce(sum(observation_count), 0) from marts.fact_player_activity_daily
                 where data_resolution = '5min')::bigint                             as readings,
            (select count(*) from marts.fact_price_snapshot)                         as price_changes,
            (select count(distinct shop_id) from marts.fact_price_snapshot)          as shops,
            (select count(*) from marts.fact_reviews)                                as reviews
    """).iloc[0]


def local(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(LOCAL_TZ)


def live_snapshot() -> pd.DataFrame:
    """Per game from the live hourly feed: latest reading, 24-hour peak, 7-day average, and how the 7-day
    average compares with the last complete month (the latest month in fact_player_activity_monthly)."""
    return query("""
        with hourly as (
            select steam_app_id, player_count, recorded_at
            from marts.fact_player_activity
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
            from marts.fact_player_activity_monthly
            where activity_month = (select max(activity_month) from marts.fact_player_activity_monthly)
        )
        select g.steam_app_id, g.name, p.now_players, p.now_at, p.peak_24h, p.avg_7d,
               m.last_month, m.last_month_avg,
               p.avg_7d / nullif(m.last_month_avg, 0) - 1 as vs_last_month
        from marts.dim_game g
        join per_game p using (steam_app_id)
        left join last_month m using (steam_app_id)
        order by g.name
    """)


def chart_block(title: str, how: str, chart, meaning: str, how_label: str | None = "How to read this",
                baseline: str | None = None, details: str | None = None, **chart_kwargs):
    """Every chart ships with a finding-title, a 'how to read' line and a 'what this means' line.
    `how` stays at two short sentences at most; the rest (definitions, counts, interactions) goes in `details`,
    shown behind the (?) icon of that line. how_label=None shows `how` as a plain one-line caption.
    baseline: one line right under an indexed chart saying what its 100% is in players (see baseline_range).
    chart_kwargs go to st.altair_chart (key / on_select / selection_mode for clickable charts); its return value
    is passed back."""
    st.markdown(f"#### {title}")
    st.caption(f"**{how_label}:** {how}" if how_label else how, help=details)
    event = st.altair_chart(style(chart), width="stretch", theme=None, **chart_kwargs)
    if baseline:
        st.caption(f":material/straighten: {baseline}")
    st.markdown(f"**What this means:** {meaning}")
    st.write("")
    return event


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

HOVER_HINT = "Hover a line to highlight that game; click a legend entry to show only that group (click again to reset)."
LEGEND_HINT = "Click a legend entry to show only that group (click again to reset)."


def legend_filter(field: str):
    """Click a legend entry to fade everything else. Runs in the browser only (no rerun).
    Bound to the legend, so clicks on the marks themselves are left free for other interactions."""
    return alt.selection_point(fields=[field], bind="legend")


def highlight_lines(lines: alt.Chart, legend_field: str) -> list[alt.Chart]:
    """Multi-line chart interactions, all in the browser (no rerun): hovering a line thickens it and fades
    the others; clicking a legend entry keeps only that group. `lines` must have a 'name' field per line.
    A transparent, wider copy of each line sits on top so the thin lines are easy to hit with the mouse.
    Tested in the browser (Altair 6.3 / Streamlit 1.64): the legend param must sit on the coloured layer, and the
    hover copy must be a separate chart without colour. Deriving both layers from `lines` makes Vega fail with
    "Duplicate signal name" (chart disappears); putting the legend param on the copy leaves the legend dead.
    Returns two layers to spread into ONE flat alt.layer(...): nesting them inside another layer makes Altair
    attach both params to both layers, which brings the "Duplicate signal name" error back."""
    hover = alt.selection_point(fields=["name"], on="pointerover", clear="pointerout")
    legend = legend_filter(legend_field)
    visible = lines.encode(
        opacity=alt.when(hover & legend).then(alt.value(0.95)).otherwise(alt.value(0.12)),
        strokeWidth=alt.when(hover, empty=False).then(alt.value(3.5)).otherwise(alt.value(2)),
    ).add_params(legend)
    enc = lines.encoding
    hit = alt.Chart(lines.data).mark_line(strokeWidth=12, strokeOpacity=0.001).encode(
        x=enc.x, y=enc.y, detail="name:N", tooltip=enc.tooltip).add_params(hover)
    return [visible, hit]


def spread_labels(ends: pd.DataFrame, ycol: str, min_gap: float) -> pd.DataFrame:
    """Nudge line-end labels apart vertically so none overlap (adds column 'label_y')."""
    out = ends.sort_values(ycol).copy()
    ys = out[ycol].tolist()
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    out["label_y"] = ys
    return out


VIEW_PCT, VIEW_PLAYERS = "% of own baseline", "Players"


def view_toggle(key: str) -> bool:
    """Players / % switch above an indexed chart. Returns True for % of own baseline (the default)."""
    return st.segmented_control("Show", [VIEW_PCT, VIEW_PLAYERS], default=VIEW_PCT, required=True, key=key,
                                label_visibility="collapsed") == VIEW_PCT


def pct(x: float, signed: bool = False) -> str:
    return f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%"


def players(x: float) -> str:
    return f"{x:,.0f}"


def share_of(label: str, value: float, base: float, base_name: str) -> str:
    """Tooltip sentence behind an indexed point, e.g. 'Month 3: 12,340 players = 47% of launch peak 26,100'."""
    return f"{label}: {players(value)} players = {pct(value / base)} of {base_name} {players(base)}"


def baseline_range(items: pd.DataFrame, value: str, label: str, what: str, across: str) -> str:
    """The spread of a chart's 100% across what the chart includes, computed from the data:
    lowest (which), median, highest (which). items: one row per game (or discount); `label` names each row."""
    v = items.dropna(subset=[value])
    lo, hi = v.loc[v[value].idxmin()], v.loc[v[value].idxmax()]
    return (f"**{what}** across {across}: lowest {players(lo[value])} players ({lo[label]}), "
            f"median {players(v[value].median())}, highest {players(hi[value])} ({hi[label]}).")


def middle_row(df: pd.DataFrame, col: str) -> pd.Series:
    """The row at the median of `col` (the lower of the two middle rows when the count is even)."""
    return df.sort_values(col).iloc[(len(df) - 1) // 2]


def game_image(url: str | None, width: int = 230) -> None:
    if url:
        st.image(url, width=width)


# ---------------------------------------------------------------------------
# Day-level charts (Q3 / Q4 detail) use UTC days from the reporting models; no day is derived here.
# ---------------------------------------------------------------------------
DAY_AXIS = "Date (UTC)"


def utc(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert("UTC")


def sale_bands(sales: pd.DataFrame, x_dom: list) -> list[alt.Chart]:
    """Steam discount periods as translucent bands (0 or 1 layer), clipped to the x domain."""
    if sales.empty:
        return []
    s = sales.copy()
    s["sale_start"] = pd.to_datetime(s["sale_start"])
    s["sale_end_x"] = pd.to_datetime(s["sale_end"]) + pd.Timedelta(days=1)
    s = s[(s["sale_end_x"] >= x_dom[0]) & (s["sale_start"] <= x_dom[1])]
    s["legend"] = "Steam discount"
    return [
        alt.Chart(s).mark_rect(opacity=0.28).encode(
            x=alt.X("sale_start:T", scale=alt.Scale(domain=x_dom)), x2="sale_end_x:T",
            color=alt.Color("legend:N", title=None, scale=alt.Scale(domain=["Steam discount"], range=[SALE_WASH])),
            tooltip=[alt.Tooltip("sale_start:T", title="Discount started", format="%d %b %Y"),
                     alt.Tooltip("sale_end:T", title="Discount ended", format="%d %b %Y"),
                     alt.Tooltip("max_discount_pct:Q", title="Discount %")],
        )
    ]


# Shown at the bottom of every page (dashboard/home.py). Licences: Mendeley dataset CC BY 4.0 (attribution required),
# Kaggle dataset CC0; Steam and IsThereAnyDeal data used under their API terms.
SOURCES_FOOTER = (
    "**Data sources.** Data powered by Steam (player counts, game details, review votes); not affiliated with or "
    "endorsed by Valve. Prices: [IsThereAnyDeal](https://isthereanydeal.com). Monthly players: "
    "[SteamCharts](https://steamcharts.com). 5-minute player history 2017–2020: Mendeley dataset \"Steam Games "
    "Dataset: Player count history, Price history and data about games\" "
    "([doi:10.17632/ycy3sy3vj2.1](https://doi.org/10.17632/ycy3sy3vj2.1)), "
    "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), shown only as daily aggregates and the results derived "
    "from them. Validation only, no data shown: Kaggle \"Steam Monthly Average Players\" by Victor Laputsky (CC0). "
    "Collection frozen on 7 Oct 2026."
)


def sources_footer() -> None:
    st.divider()
    st.caption(SOURCES_FOOTER)
