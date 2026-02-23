import os
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Kcal Tracker", page_icon="🍽️", layout="wide")

# ----------------------------
# DB
# ----------------------------
def get_database_url() -> str | None:
    # Streamlit Cloud: st.secrets["DATABASE_URL"]
    if "DATABASE_URL" in st.secrets:
        return st.secrets["DATABASE_URL"]
    # Local: env var
    return os.environ.get("DATABASE_URL")


@st.cache_resource
def get_engine():
    db_url = get_database_url()
    if not db_url:
        # fallback local SQLite (OK locally, not for cloud persistence)
        return create_engine("sqlite:///kcal_tracker.db", future=True)
    return create_engine(db_url, future=True, pool_pre_ping=True)


def ensure_schema():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily (
                day DATE PRIMARY KEY,

                meal1_kcal INTEGER DEFAULT 0, meal1_p REAL DEFAULT 0, meal1_c REAL DEFAULT 0, meal1_f REAL DEFAULT 0,
                meal2_kcal INTEGER DEFAULT 0, meal2_p REAL DEFAULT 0, meal2_c REAL DEFAULT 0, meal2_f REAL DEFAULT 0,
                meal3_kcal INTEGER DEFAULT 0, meal3_p REAL DEFAULT 0, meal3_c REAL DEFAULT 0, meal3_f REAL DEFAULT 0,
                add_kcal  INTEGER DEFAULT 0, add_p  REAL DEFAULT 0, add_c  REAL DEFAULT 0, add_f  REAL DEFAULT 0,

                steps INTEGER DEFAULT 0,
                kcal_per_step REAL DEFAULT 0.04,
                steps_kcal REAL DEFAULT 0,

                training_name TEXT DEFAULT '',
                training_kcal REAL DEFAULT 0,

                weight REAL,

                total_kcal INTEGER DEFAULT 0,
                total_p REAL DEFAULT 0,
                total_c REAL DEFAULT 0,
                total_f REAL DEFAULT 0,
                net_kcal REAL DEFAULT 0,

                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """))

        # defaults
        defaults = {
            "goal_kcal": "2200",
            "goal_protein": "210",
            "goal_fat": "85",
            "goal_carbs": "150",
            "goal_steps": "8000",
            "kcal_per_step": "0.04",
            "kcal_yellow_over": "200",
            "steps_yellow_gap": "2000",
        }
        for k, v in defaults.items():
            conn.execute(text("""
                INSERT INTO settings(key, value) VALUES (:k, :v)
                ON CONFLICT (key) DO NOTHING
            """), {"k": k, "v": v})


def get_settings() -> dict:
    eng = get_engine()
    df = pd.read_sql(text("SELECT key, value FROM settings"), eng)
    return {r["key"]: r["value"] for _, r in df.iterrows()}


def set_setting(key: str, value: str):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO settings(key, value) VALUES (:k, :v)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """), {"k": key, "v": value})


def upsert_day(row: dict):
    eng = get_engine()
    now = datetime.now()
    with eng.begin() as conn:
        # insert or update
        # PostgreSQL uses ON CONFLICT; SQLite also supports it
        conn.execute(text("""
            INSERT INTO daily (
                day,
                meal1_kcal, meal1_p, meal1_c, meal1_f,
                meal2_kcal, meal2_p, meal2_c, meal2_f,
                meal3_kcal, meal3_p, meal3_c, meal3_f,
                add_kcal, add_p, add_c, add_f,
                steps, kcal_per_step, steps_kcal,
                training_name, training_kcal,
                weight,
                total_kcal, total_p, total_c, total_f, net_kcal,
                created_at, updated_at
            )
            VALUES (
                :day,
                :meal1_kcal, :meal1_p, :meal1_c, :meal1_f,
                :meal2_kcal, :meal2_p, :meal2_c, :meal2_f,
                :meal3_kcal, :meal3_p, :meal3_c, :meal3_f,
                :add_kcal, :add_p, :add_c, :add_f,
                :steps, :kcal_per_step, :steps_kcal,
                :training_name, :training_kcal,
                :weight,
                :total_kcal, :total_p, :total_c, :total_f, :net_kcal,
                :created_at, :updated_at
            )
            ON CONFLICT (day) DO UPDATE SET
                meal1_kcal=excluded.meal1_kcal, meal1_p=excluded.meal1_p, meal1_c=excluded.meal1_c, meal1_f=excluded.meal1_f,
                meal2_kcal=excluded.meal2_kcal, meal2_p=excluded.meal2_p, meal2_c=excluded.meal2_c, meal2_f=excluded.meal2_f,
                meal3_kcal=excluded.meal3_kcal, meal3_p=excluded.meal3_p, meal3_c=excluded.meal3_c, meal3_f=excluded.meal3_f,
                add_kcal=excluded.add_kcal, add_p=excluded.add_p, add_c=excluded.add_c, add_f=excluded.add_f,
                steps=excluded.steps, kcal_per_step=excluded.kcal_per_step, steps_kcal=excluded.steps_kcal,
                training_name=excluded.training_name, training_kcal=excluded.training_kcal,
                weight=excluded.weight,
                total_kcal=excluded.total_kcal, total_p=excluded.total_p, total_c=excluded.total_c, total_f=excluded.total_f,
                net_kcal=excluded.net_kcal,
                updated_at=excluded.updated_at
        """), {
            **row,
            "created_at": row.get("created_at") or now,
            "updated_at": now,
        })


def delete_day(day_: date):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM daily WHERE day = :d"), {"d": day_})


def load_history() -> pd.DataFrame:
    eng = get_engine()
    df = pd.read_sql(text("""
        SELECT
            day,
            steps,
            steps_kcal,
            training_name,
            training_kcal,
            weight,
            total_kcal,
            total_p,
            total_c,
            total_f,
            net_kcal
        FROM daily
        ORDER BY day ASC
    """), eng)
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"]).dt.date
    return df


# ----------------------------
# Goals + zones
# ----------------------------
def to_int(x, default=0):
    try:
        return int(float(str(x).replace(",", ".")))
    except Exception:
        return default


def to_float(x, default=0.0):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return default


def zone_kcal(value: float, goal: float, yellow_over: float) -> str:
    if value <= goal:
        return "green"
    if value <= goal + yellow_over:
        return "yellow"
    return "red"


def zone_steps(steps: int, goal_steps: int, yellow_gap: int) -> str:
    if steps >= goal_steps:
        return "green"
    if steps >= max(0, goal_steps - yellow_gap):
        return "yellow"
    return "red"


def zone_macro(value: float, goal: float) -> str:
    # green: 90–110%, yellow: 75–90 or 110–125, red otherwise
    if goal <= 0:
        return "green"
    low_g, high_g = 0.90 * goal, 1.10 * goal
    low_y, high_y = 0.75 * goal, 1.25 * goal
    if low_g <= value <= high_g:
        return "green"
    if low_y <= value <= high_y:
        return "yellow"
    return "red"


def emoji(z: str) -> str:
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(z, "⚪")


def color_for_zone(z: str) -> str:
    return {"green": "#1b7f3a", "yellow": "#b8860b", "red": "#b00020"}.get(z, "#000000")


# ----------------------------
# App
# ----------------------------
ensure_schema()
settings = get_settings()

goal_kcal = to_float(settings.get("goal_kcal", 2200), 2200)
goal_p = to_float(settings.get("goal_protein", 210), 210)
goal_f = to_float(settings.get("goal_fat", 85), 85)
goal_c = to_float(settings.get("goal_carbs", 150), 150)
goal_steps = to_int(settings.get("goal_steps", 8000), 8000)
kcal_per_step_default = to_float(settings.get("kcal_per_step", 0.04), 0.04)
kcal_yellow_over = to_float(settings.get("kcal_yellow_over", 200), 200)
steps_yellow_gap = to_int(settings.get("steps_yellow_gap", 2000), 2000)

st.title("🍽️ Kcal Tracker")
st.caption("Wpisy dzienne • historia • wykresy z tooltipami • cele i progi kolorów")

tab_entry, tab_history, tab_charts, tab_settings = st.tabs(["Wpis", "Historia", "Wykresy", "Cele / Ustawienia"])

# ----------------------------
# Entry
# ----------------------------
with tab_entry:
    colA, colB = st.columns([1.2, 1.0], gap="large")

    with colA:
        st.subheader("Wpis dnia")
        d = st.date_input("Data", value=date.today())

        st.markdown("### Posiłki")
        def meal_block(title: str, key: str):
            st.markdown(f"**{title}**")
            c1, c2, c3, c4 = st.columns(4)
            kcal = c1.number_input("kcal", min_value=0, step=10, key=f"{key}_kcal")
            p = c2.number_input("B (g)", min_value=0.0, step=1.0, key=f"{key}_p")
            c = c3.number_input("W (g)", min_value=0.0, step=1.0, key=f"{key}_c")
            f = c4.number_input("T (g)", min_value=0.0, step=1.0, key=f"{key}_f")
            return kcal, p, c, f

        meal1 = meal_block("1 posiłek", "m1")
        meal2 = meal_block("2 posiłek", "m2")
        meal3 = meal_block("3 posiłek", "m3")
        add  = meal_block("Dodatki", "add")

        st.markdown("### Aktywność")
        c1, c2, c3 = st.columns(3)
        steps = c1.number_input("Kroki", min_value=0, step=500, value=0)
        kcal_per_step = c2.number_input(
            "kcal / krok",
            min_value=0.0,
            step=0.01,
            value=float(kcal_per_step_default),
            key="entry_kcal_per_step"
        )
        weight = c3.number_input("Waga (kg)", min_value=0.0, step=0.1, value=0.0)

        c4, c5 = st.columns([1.6, 0.8])
        training_name = c4.text_input("Trening (nazwa)", value="")
        training_kcal = c5.number_input("Trening (kcal spalone)", min_value=0.0, step=10.0, value=0.0)

        # totals
        food_kcal = meal1[0] + meal2[0] + meal3[0] + add[0]
        total_p = meal1[1] + meal2[1] + meal3[1] + add[1]
        total_c = meal1[2] + meal2[2] + meal3[2] + add[2]
        total_f = meal1[3] + meal2[3] + meal3[3] + add[3]

        steps_kcal = steps * kcal_per_step
        net_kcal = food_kcal - steps_kcal - training_kcal

        st.markdown("### Podsumowanie (kolory wg celów)")
        z_food = zone_kcal(food_kcal, goal_kcal, kcal_yellow_over)
        z_net = zone_kcal(net_kcal, goal_kcal, kcal_yellow_over)
        z_p = zone_macro(total_p, goal_p)
        z_c = zone_macro(total_c, goal_c)
        z_f = zone_macro(total_f, goal_f)
        z_steps = zone_steps(steps, goal_steps, steps_yellow_gap)

        m1c, m2c, m3c, m4c, m5c, m6c = st.columns(6)
        m1c.metric("kcal jedzenie", f"{food_kcal:.0f}", delta=f"cel {goal_kcal:.0f}", delta_color="off")
        m2c.metric("kcal netto", f"{net_kcal:.0f}", delta=f"cel {goal_kcal:.0f}", delta_color="off")
        m3c.metric("B (g)", f"{total_p:.0f}", delta=f"cel {goal_p:.0f}", delta_color="off")
        m4c.metric("W (g)", f"{total_c:.0f}", delta=f"cel {goal_c:.0f}", delta_color="off")
        m5c.metric("T (g)", f"{total_f:.0f}", delta=f"cel {goal_f:.0f}", delta_color="off")
        m6c.metric("Kroki", f"{steps}", delta=f"cel {goal_steps}", delta_color="off")

        st.markdown(
            f"""
            **Status:**  
            kcal jedzenie {emoji(z_food)} • kcal netto {emoji(z_net)} • białko {emoji(z_p)} • węgle {emoji(z_c)} • tłuszcz {emoji(z_f)} • kroki {emoji(z_steps)}
            """
        )

        save = st.button("💾 Zapisz dzień", type="primary")

        if save:
            row = {
                "day": d,
                "meal1_kcal": int(meal1[0]), "meal1_p": float(meal1[1]), "meal1_c": float(meal1[2]), "meal1_f": float(meal1[3]),
                "meal2_kcal": int(meal2[0]), "meal2_p": float(meal2[1]), "meal2_c": float(meal2[2]), "meal2_f": float(meal2[3]),
                "meal3_kcal": int(meal3[0]), "meal3_p": float(meal3[1]), "meal3_c": float(meal3[2]), "meal3_f": float(meal3[3]),
                "add_kcal": int(add[0]), "add_p": float(add[1]), "add_c": float(add[2]), "add_f": float(add[3]),
                "steps": int(steps),
                "kcal_per_step": float(kcal_per_step),
                "steps_kcal": float(steps_kcal),
                "training_name": training_name,
                "training_kcal": float(training_kcal),
                "weight": (None if weight == 0 else float(weight)),
                "total_kcal": int(food_kcal),
                "total_p": float(total_p),
                "total_c": float(total_c),
                "total_f": float(total_f),
                "net_kcal": float(net_kcal),
            }
            upsert_day(row)
            st.success(f"Zapisano dzień {d} ✅")

    with colB:
        st.subheader("Przedziały kolorów (podgląd)")
        st.write(
            f"""
            **Kcal:** 🟢 ≤ {goal_kcal:.0f} • 🟡 {goal_kcal:.0f}–{(goal_kcal+kcal_yellow_over):.0f} • 🔴 > {(goal_kcal+kcal_yellow_over):.0f}  
            **Białko:** 🟢 {0.90*goal_p:.0f}–{1.10*goal_p:.0f} • 🟡 {0.75*goal_p:.0f}–{1.25*goal_p:.0f} • 🔴 poza  
            **Węgle:** 🟢 {0.90*goal_c:.0f}–{1.10*goal_c:.0f} • 🟡 {0.75*goal_c:.0f}–{1.25*goal_c:.0f} • 🔴 poza  
            **Tłuszcz:** 🟢 {0.90*goal_f:.0f}–{1.10*goal_f:.0f} • 🟡 {0.75*goal_f:.0f}–{1.25*goal_f:.0f} • 🔴 poza  
            **Kroki:** 🟢 ≥ {goal_steps} • 🟡 {max(0, goal_steps-steps_yellow_gap)}–{max(0, goal_steps-1)} • 🔴 < {max(0, goal_steps-steps_yellow_gap)}
            """
        )

# ----------------------------
# History
# ----------------------------
with tab_history:
    st.subheader("Historia")
    df = load_history()

    if df.empty:
        st.info("Brak zapisów jeszcze.")
    else:
        # Add statuses per metric
        df2 = df.copy()
        df2["S kcal"] = df2["net_kcal"].apply(lambda v: emoji(zone_kcal(v, goal_kcal, kcal_yellow_over)))
        df2["S B"] = df2["total_p"].apply(lambda v: emoji(zone_macro(v, goal_p)))
        df2["S W"] = df2["total_c"].apply(lambda v: emoji(zone_macro(v, goal_c)))
        df2["S T"] = df2["total_f"].apply(lambda v: emoji(zone_macro(v, goal_f)))
        df2["S kroki"] = df2["steps"].apply(lambda v: emoji(zone_steps(int(v or 0), goal_steps, steps_yellow_gap)))

        # styling per cell
        def style_zone(val, zfunc, *args):
            z = zfunc(val, *args)
            return f"color: {color_for_zone(z)}; font-weight: 600;"

        styled = df2.style \
            .applymap(lambda v: style_zone(v, zone_kcal, goal_kcal, kcal_yellow_over), subset=["net_kcal"]) \
            .applymap(lambda v: style_zone(v, zone_kcal, goal_kcal, kcal_yellow_over), subset=["total_kcal"]) \
            .applymap(lambda v: style_zone(v, zone_macro, goal_p), subset=["total_p"]) \
            .applymap(lambda v: style_zone(v, zone_macro, goal_c), subset=["total_c"]) \
            .applymap(lambda v: style_zone(v, zone_macro, goal_f), subset=["total_f"]) \
            .applymap(lambda v: style_zone(int(v or 0), zone_steps, goal_steps, steps_yellow_gap), subset=["steps"])

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "day": st.column_config.DateColumn("Data"),
                "steps": st.column_config.NumberColumn("Kroki"),
                "steps_kcal": st.column_config.NumberColumn("kcal kroki", format="%.0f"),
                "training_name": st.column_config.TextColumn("Trening"),
                "training_kcal": st.column_config.NumberColumn("kcal trening", format="%.0f"),
                "weight": st.column_config.NumberColumn("Waga (kg)", format="%.1f"),
                "total_kcal": st.column_config.NumberColumn("kcal jedzenie", format="%d"),
                "net_kcal": st.column_config.NumberColumn("kcal netto", format="%.0f"),
                "total_p": st.column_config.NumberColumn("B (g)", format="%.1f"),
                "total_c": st.column_config.NumberColumn("W (g)", format="%.1f"),
                "total_f": st.column_config.NumberColumn("T (g)", format="%.1f"),
            }
        )

        st.markdown("---")
        st.subheader("Usuń dzień")

        del_col1, del_col2 = st.columns([1, 1])
        with del_col1:
            day_to_delete = st.selectbox("Wybierz datę do usunięcia", options=list(df2["day"].tolist()))
        with del_col2:
            if st.button("🗑️ Usuń wybrany dzień", type="secondary"):
                delete_day(day_to_delete)
                st.success(f"Usunięto {day_to_delete}. Odśwież stronę / przełącz zakładkę.")
                st.rerun()

# ----------------------------
# Charts (Altair tooltips)
# ----------------------------
with tab_charts:
    st.subheader("Wykresy (najeżdżaj palcem/myszką — tooltips)")
    df = load_history()

    if df.empty:
        st.info("Brak danych do wykresów.")
    else:
        c1, c2 = st.columns(2, gap="large")

        with c1:
            st.markdown("### Kroki dziennie")
            steps_df = df[["day", "steps"]].copy()
            steps_df["day"] = pd.to_datetime(steps_df["day"])
            chart_steps = alt.Chart(steps_df).mark_bar().encode(
                x=alt.X("day:T", title="Data"),
                y=alt.Y("steps:Q", title="Kroki"),
                tooltip=[alt.Tooltip("day:T", title="Data"), alt.Tooltip("steps:Q", title="Kroki")]
            ).interactive()
            st.altair_chart(chart_steps, use_container_width=True)

        with c2:
            st.markdown("### Waga")
            wdf = df.dropna(subset=["weight"])[["day", "weight"]].copy()
            if wdf.empty:
                st.info("Brak wpisów wagi.")
            else:
                wdf["day"] = pd.to_datetime(wdf["day"])
                chart_weight = alt.Chart(wdf).mark_line(point=True).encode(
                    x=alt.X("day:T", title="Data"),
                    y=alt.Y("weight:Q", title="kg"),
                    tooltip=[alt.Tooltip("day:T", title="Data"), alt.Tooltip("weight:Q", title="Waga (kg)", format=".1f")]
                ).interactive()
                st.altair_chart(chart_weight, use_container_width=True)

        st.markdown("### Bonus: kcal netto (bardzo przydatne na redukcji)")
        ndf = df[["day", "net_kcal", "total_kcal", "steps_kcal", "training_kcal"]].copy()
        ndf["day"] = pd.to_datetime(ndf["day"])
        chart_net = alt.Chart(ndf).mark_line(point=True).encode(
            x=alt.X("day:T", title="Data"),
            y=alt.Y("net_kcal:Q", title="kcal netto"),
            tooltip=[
                alt.Tooltip("day:T", title="Data"),
                alt.Tooltip("net_kcal:Q", title="kcal netto", format=".0f"),
                alt.Tooltip("total_kcal:Q", title="kcal jedzenie", format=".0f"),
                alt.Tooltip("steps_kcal:Q", title="kcal kroki", format=".0f"),
                alt.Tooltip("training_kcal:Q", title="kcal trening", format=".0f"),
            ]
        ).interactive()
        st.altair_chart(chart_net, use_container_width=True)

# ----------------------------
# Settings
# ----------------------------
with tab_settings:
    st.subheader("Cele / Ustawienia")

    st.markdown("### Cele")
    c1, c2, c3 = st.columns(3)
    new_goal_kcal = c1.number_input("Cel kcal (jedzenie / netto)", min_value=0, step=50, value=int(goal_kcal))
    new_goal_steps = c2.number_input("Cel kroków", min_value=0, step=500, value=int(goal_steps))
    new_kps = c3.number_input(
        "kcal / krok",
        min_value=0.0,
        step=0.01,
        value=float(kcal_per_step_default),
        key="settings_kcal_per_step"
    )

    c4, c5, c6 = st.columns(3)
    new_p = c4.number_input("Cel białko (g)", min_value=0.0, step=5.0, value=float(goal_p))
    new_c = c5.number_input("Cel węgle (g)", min_value=0.0, step=5.0, value=float(goal_c))
    new_f = c6.number_input("Cel tłuszcz (g)", min_value=0.0, step=5.0, value=float(goal_f))

    st.markdown("### Progi kolorów")
    c7, c8 = st.columns(2)
    new_kcal_yellow_over = c7.number_input("kcal: żółty do (cel + ...)", min_value=0.0, step=50.0, value=float(kcal_yellow_over))
    new_steps_yellow_gap = c8.number_input("kroki: żółty jeśli poniżej celu o max ...", min_value=0, step=500, value=int(steps_yellow_gap))

    if st.button("💾 Zapisz ustawienia", type="primary"):
        set_setting("goal_kcal", str(int(new_goal_kcal)))
        set_setting("goal_steps", str(int(new_goal_steps)))
        set_setting("kcal_per_step", str(float(new_kps)))
        set_setting("goal_protein", str(float(new_p)))
        set_setting("goal_carbs", str(float(new_c)))
        set_setting("goal_fat", str(float(new_f)))
        set_setting("kcal_yellow_over", str(float(new_kcal_yellow_over)))
        set_setting("steps_yellow_gap", str(int(new_steps_yellow_gap)))
        st.success("Zapisano ✅")
        st.rerun()

    st.markdown("---")
    st.subheader("Podgląd przedziałów (z Twoich ustawień)")
    st.write(
        f"""
        **Kcal:** 🟢 ≤ {new_goal_kcal:.0f} • 🟡 {new_goal_kcal:.0f}–{(new_goal_kcal+new_kcal_yellow_over):.0f} • 🔴 > {(new_goal_kcal+new_kcal_yellow_over):.0f}  
        **Białko:** 🟢 {0.90*new_p:.0f}–{1.10*new_p:.0f} • 🟡 {0.75*new_p:.0f}–{1.25*new_p:.0f} • 🔴 poza  
        **Węgle:** 🟢 {0.90*new_c:.0f}–{1.10*new_c:.0f} • 🟡 {0.75*new_c:.0f}–{1.25*new_c:.0f} • 🔴 poza  
        **Tłuszcz:** 🟢 {0.90*new_f:.0f}–{1.10*new_f:.0f} • 🟡 {0.75*new_f:.0f}–{1.25*new_f:.0f} • 🔴 poza  
        **Kroki:** 🟢 ≥ {int(new_goal_steps)} • 🟡 {max(0, int(new_goal_steps - new_steps_yellow_gap))}–{max(0, int(new_goal_steps-1))} • 🔴 < {max(0, int(new_goal_steps - new_steps_yellow_gap))}
        """
    )