import os
from datetime import date
import pandas as pd
import streamlit as st
import altair as alt

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# ----------------------------
# APP CONFIG
# ----------------------------
st.set_page_config(page_title="Fit Tracker", page_icon="🍽️", layout="wide")

# ----------------------------
# "AUTH" - 2 users via PIN
# ----------------------------
USERS = {
    "Kacper": {"pin": "1111", "user_id": 1},
    "Klaudia": {"pin": "2222", "user_id": 2},
}

# ----------------------------
# DB helpers
# ----------------------------
def get_database_url() -> str | None:
    if "DATABASE_URL" in st.secrets:
        return st.secrets["DATABASE_URL"]
    return os.environ.get("DATABASE_URL")


@st.cache_resource
def get_engine():
    db_url = get_database_url()
    if not db_url:
        raise RuntimeError(
            "Brak DATABASE_URL. Ustaw w Streamlit Cloud -> Settings -> Secrets "
            "albo lokalnie jako zmienną środowiskową DATABASE_URL."
        )

    # Supabase Pooler (PgBouncer) / stabilne zachowanie:
    return create_engine(
        db_url,
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args={"options": "-csearch_path=public"},
    )


def ensure_schema():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                """
            create table if not exists public.settings (
                user_id bigint not null,
                key text not null,
                value text not null,
                updated_at timestamptz default now(),
                primary key (user_id, key)
            );
        """
            )
        )

        conn.execute(
            text(
                """
            create table if not exists public.daily (
                user_id bigint not null,
                day date not null,

                kcal_m1 numeric default 0,
                p_m1 numeric default 0,
                c_m1 numeric default 0,
                f_m1 numeric default 0,

                kcal_m2 numeric default 0,
                p_m2 numeric default 0,
                c_m2 numeric default 0,
                f_m2 numeric default 0,

                kcal_m3 numeric default 0,
                p_m3 numeric default 0,
                c_m3 numeric default 0,
                f_m3 numeric default 0,

                kcal_add numeric default 0,
                p_add numeric default 0,
                c_add numeric default 0,
                f_add numeric default 0,

                steps integer default 0,
                kcal_per_step numeric default 0.04,
                weight numeric,
                training_name text,
                training_kcal numeric default 0,

                created_at timestamptz default now(),
                updated_at timestamptz default now(),

                primary key (user_id, day)
            );
        """
            )
        )

        # --- DODATEK: POMIARY CIAŁA (bezpieczna "migracja" dla istniejącej tabeli) ---
        conn.execute(text("""alter table public.daily add column if not exists waist_cm numeric;"""))
        conn.execute(text("""alter table public.daily add column if not exists biceps_cm numeric;"""))
        conn.execute(text("""alter table public.daily add column if not exists chest_cm numeric;"""))


def get_setting(conn, user_id: int, key: str, default: str) -> str:
    row = (
        conn.execute(
            text("select value from public.settings where user_id=:uid and key=:k"),
            {"uid": user_id, "k": key},
        )
        .mappings()
        .first()
    )
    return row["value"] if row else default


def set_setting(conn, user_id: int, key: str, value: str):
    conn.execute(
        text(
            """
        insert into public.settings (user_id, key, value, updated_at)
        values (:uid, :k, :v, now())
        on conflict (user_id, key)
        do update set value = excluded.value, updated_at = now()
    """
        ),
        {"uid": user_id, "k": key, "v": value},
    )


def load_day(conn, user_id: int, d: date) -> dict | None:
    row = (
        conn.execute(
            text("select * from public.daily where user_id=:uid and day=:d"),
            {"uid": user_id, "d": d},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def upsert_day(conn, user_id: int, d: date, payload: dict):
    payload = {**payload, "user_id": user_id, "day": d}
    conn.execute(
        text(
            """
        insert into public.daily (
            user_id, day,
            kcal_m1, p_m1, c_m1, f_m1,
            kcal_m2, p_m2, c_m2, f_m2,
            kcal_m3, p_m3, c_m3, f_m3,
            kcal_add, p_add, c_add, f_add,
            steps, kcal_per_step, weight,
            training_name, training_kcal,
            waist_cm, biceps_cm, chest_cm,
            updated_at
        ) values (
            :user_id, :day,
            :kcal_m1, :p_m1, :c_m1, :f_m1,
            :kcal_m2, :p_m2, :c_m2, :f_m2,
            :kcal_m3, :p_m3, :c_m3, :f_m3,
            :kcal_add, :p_add, :c_add, :f_add,
            :steps, :kcal_per_step, :weight,
            :training_name, :training_kcal,
            :waist_cm, :biceps_cm, :chest_cm,
            now()
        )
        on conflict (user_id, day)
        do update set
            kcal_m1=excluded.kcal_m1, p_m1=excluded.p_m1, c_m1=excluded.c_m1, f_m1=excluded.f_m1,
            kcal_m2=excluded.kcal_m2, p_m2=excluded.p_m2, c_m2=excluded.c_m2, f_m2=excluded.f_m2,
            kcal_m3=excluded.kcal_m3, p_m3=excluded.p_m3, c_m3=excluded.c_m3, f_m3=excluded.f_m3,
            kcal_add=excluded.kcal_add, p_add=excluded.p_add, c_add=excluded.c_add, f_add=excluded.f_add,
            steps=excluded.steps, kcal_per_step=excluded.kcal_per_step, weight=excluded.weight,
            training_name=excluded.training_name, training_kcal=excluded.training_kcal,
            waist_cm=excluded.waist_cm, biceps_cm=excluded.biceps_cm, chest_cm=excluded.chest_cm,
            updated_at=now()
    """
        ),
        payload,
    )


def delete_day(conn, user_id: int, d: date):
    conn.execute(
        text("delete from public.daily where user_id=:uid and day=:d"),
        {"uid": user_id, "d": d},
    )


def load_history(conn, user_id: int) -> pd.DataFrame:
    df = pd.read_sql(
        text("select * from public.daily where user_id=:uid order by day desc"),
        conn,
        params={"uid": user_id},
    )
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


# ----------------------------
# FORM CLEAR (safe with rerun flag)
# ----------------------------
def clear_day_form(keep_kcal_per_step: bool = True):
    numeric_keys = [
        "entry_m1_kcal",
        "entry_m1_p",
        "entry_m1_c",
        "entry_m1_f",
        "entry_m2_kcal",
        "entry_m2_p",
        "entry_m2_c",
        "entry_m2_f",
        "entry_m3_kcal",
        "entry_m3_p",
        "entry_m3_c",
        "entry_m3_f",
        "entry_add_kcal",
        "entry_add_p",
        "entry_add_c",
        "entry_add_f",
        "entry_steps",
        "entry_weight",
        "entry_training_kcal",

        # --- DODATEK: POMIARY CIAŁA ---
        "entry_weight_body",
        "entry_waist",
        "entry_biceps",
        "entry_chest",
    ]
    text_keys = ["entry_training_name"]

    if not keep_kcal_per_step:
        numeric_keys.append("entry_kcal_per_step")

    for k in numeric_keys:
        if k in st.session_state:
            st.session_state[k] = 0

    for k in text_keys:
        if k in st.session_state:
            st.session_state[k] = ""


# ----------------------------
# Color logic
# ----------------------------
def color_for(value: float, green_max: float, yellow_max: float) -> str:
    if value <= green_max:
        return "🟢"
    if value <= yellow_max:
        return "🟡"
    return "🔴"


def macro_status(val: float, target: float) -> str:
    g_lo, g_hi = 0.9 * target, 1.1 * target
    y_lo, y_hi = 0.75 * target, 1.25 * target
    if g_lo <= val <= g_hi:
        return "🟢"
    if (y_lo <= val < g_lo) or (g_hi < val <= y_hi):
        return "🟡"
    return "🔴"


def range_preview(kcal_target: float, protein_target: float, carbs_target: float, fat_target: float, steps_target: int):
    kcal_g = kcal_target
    kcal_y = kcal_target + 200

    def macro_ranges(t):
        g_lo, g_hi = 0.9 * t, 1.1 * t
        y_lo, y_hi = 0.75 * t, 1.25 * t
        return (g_lo, g_hi, y_lo, y_hi)

    p = macro_ranges(protein_target)
    c = macro_ranges(carbs_target)
    f = macro_ranges(fat_target)

    s_g = steps_target
    s_y = max(0, steps_target - 2000)

    st.markdown("### Przedziały kolorów (podgląd)")
    st.write(
        f"**Kalorie:** 🟢 ≤ {kcal_g:.0f} • 🟡 {kcal_g:.0f}-{kcal_y:.0f} • 🔴 > {kcal_y:.0f}\n\n"
        f"**Białko:** 🟢 {p[0]:.0f}-{p[1]:.0f} • 🟡 {p[2]:.0f}-{p[0]:.0f} lub {p[1]:.0f}-{p[3]:.0f} • 🔴 poza\n\n"
        f"**Węgle:** 🟢 {c[0]:.0f}-{c[1]:.0f} • 🟡 {c[2]:.0f}-{c[0]:.0f} lub {c[1]:.0f}-{c[3]:.0f} • 🔴 poza\n\n"
        f"**Tłuszcz:** 🟢 {f[0]:.0f}-{f[1]:.0f} • 🟡 {f[2]:.0f}-{f[0]:.0f} lub {f[1]:.0f}-{f[3]:.0f} • 🔴 poza\n\n"
        f"**Kroki:** 🟢 ≥ {s_g} • 🟡 {s_y}-{s_g - 1 if s_g > 0 else 0} • 🔴 < {s_y}"
    )


# ----------------------------
# Login UI
# ----------------------------
def login_ui():
    st.title("🍽️ Fit Tracker")
    st.caption("Wpisy dzienne • Historia • Wykresy • Cele")

    col1, col2 = st.columns([1, 2])
    with col1:
        user = st.selectbox("Wybierz profil", list(USERS.keys()), key="login_user")
        pin = st.text_input("PIN", type="password", key="login_pin")
        if st.button("Zaloguj", type="primary"):
            if pin == USERS[user]["pin"]:
                st.session_state["user_name"] = user
                st.session_state["user_id"] = USERS[user]["user_id"]
                st.rerun()
            else:
                st.error("Zły PIN.")
    with col2:
        st.info(
            "Profile:\n- Kacper (PIN 1111)\n- Klaudia (PIN 2222)\n\n"
            "Każdy profil ma osobne dane w bazie (user_id)."
        )


# ----------------------------
# MAIN
# ----------------------------
ensure_schema()

if "user_id" not in st.session_state:
    login_ui()
    st.stop()

USER_ID = int(st.session_state["user_id"])
USER_NAME = st.session_state["user_name"]

st.title("🍽️ Fit Tracker")
st.caption("Wpisy dzienne • Historia • Wykresy • Cele")

top = st.columns([3, 1])
with top[0]:
    st.success(f"Zalogowany: **{USER_NAME}**")
with top[1]:
    if st.button("Wyloguj"):
        st.session_state.clear()
        st.rerun()

eng = get_engine()

with eng.begin() as conn:
    kcal_target = float(get_setting(conn, USER_ID, "kcal_target", "2200"))
    protein_target = float(get_setting(conn, USER_ID, "protein_target", "210"))
    carbs_target = float(get_setting(conn, USER_ID, "carbs_target", "150"))
    fat_target = float(get_setting(conn, USER_ID, "fat_target", "85"))
    steps_target = int(float(get_setting(conn, USER_ID, "steps_target", "8000")))

tabs = st.tabs(["Wpis", "Historia", "Wykresy", "Cele / Ustawienia"])

# ----------------------------
# TAB: ENTRY
# ----------------------------
with tabs[0]:
    if st.session_state.get("_do_clear_form", False):
        clear_day_form(keep_kcal_per_step=True)
        st.session_state["_do_clear_form"] = False

    c_left, c_right = st.columns([2, 1])

    with c_right:
        range_preview(kcal_target, protein_target, carbs_target, fat_target, steps_target)

    with c_left:
        st.subheader("Wpis dnia")
        d = st.date_input("Data", value=date.today(), key="entry_date")

        with eng.begin() as conn:
            existing = load_day(conn, USER_ID, d)

        def ex(name: str, default=0.0) -> float:
            if existing and existing.get(name) is not None:
                return float(existing[name] or 0)
            return float(default)

        def ex_int(name: str, default=0) -> int:
            if existing and existing.get(name) is not None:
                return int(existing[name] or 0)
            return int(default)

        def ex_str(name: str, default="") -> str:
            if existing and existing.get(name) is not None:
                return str(existing[name] or "")
            return str(default)

        # --- synchronizacja wagi (Aktywność <-> Pomiary ciała) ---
        def _sync_weight_from_activity():
            st.session_state["entry_weight_body"] = float(st.session_state.get("entry_weight", 0.0) or 0.0)

        def _sync_weight_from_body():
            st.session_state["entry_weight"] = float(st.session_state.get("entry_weight_body", 0.0) or 0.0)

        st.markdown("### Posiłki")

        def meal_block(title: str, prefix: str):
            st.markdown(f"**{title}**")
            c1, c2, c3, c4 = st.columns(4)
            kcal = c1.number_input(
                "kcal", min_value=0.0, step=1.0, value=ex(f"kcal_{prefix}"), key=f"entry_{prefix}_kcal"
            )
            p = c2.number_input(
                "B (g)", min_value=0.0, step=1.0, value=ex(f"p_{prefix}"), key=f"entry_{prefix}_p"
            )
            c = c3.number_input(
                "W (g)", min_value=0.0, step=1.0, value=ex(f"c_{prefix}"), key=f"entry_{prefix}_c"
            )
            f = c4.number_input(
                "T (g)", min_value=0.0, step=1.0, value=ex(f"f_{prefix}"), key=f"entry_{prefix}_f"
            )
            return kcal, p, c, f

        kcal_m1, p_m1, c_m1, f_m1 = meal_block("1 posiłek", "m1")
        kcal_m2, p_m2, c_m2, f_m2 = meal_block("2 posiłek", "m2")
        kcal_m3, p_m3, c_m3, f_m3 = meal_block("3 posiłek", "m3")
        kcal_add, p_add, c_add, f_add = meal_block("Dodatki", "add")

        st.markdown("### Aktywność")
        a1, a2, a3 = st.columns(3)
        steps = a1.number_input("Kroki", min_value=0, step=100, value=ex_int("steps"), key="entry_steps")
        kcal_per_step = a2.number_input(
            "kcal / krok", min_value=0.0, step=0.01, value=ex("kcal_per_step", 0.04), key="entry_kcal_per_step"
        )
        weight = a3.number_input(
            "Waga (kg)",
            min_value=0.0,
            step=0.1,
            value=ex("weight", 0.0),
            key="entry_weight",
            on_change=_sync_weight_from_activity,
        )

        t1, t2 = st.columns([2, 1])
        training_name = t1.text_input("Trening (nazwa)", value=ex_str("training_name", ""), key="entry_training_name")
        training_kcal = t2.number_input(
            "Trening (kcal spalone)", min_value=0.0, step=10.0, value=ex("training_kcal", 0.0), key="entry_training_kcal"
        )

        # --- DODATEK: POMIARY CIAŁA ---
        st.markdown("### Pomiary ciała")
        p1, p2, p3, p4 = st.columns(4)
        weight_body = p1.number_input(
            "Waga (kg)",
            min_value=0.0,
            step=0.1,
            value=ex("weight", 0.0),
            key="entry_weight_body",
            on_change=_sync_weight_from_body,
        )
        waist = p2.number_input(
            "Talia (cm)",
            min_value=0.0,
            step=0.1,
            value=ex("waist_cm", 0.0),
            key="entry_waist",
        )
        biceps = p3.number_input(
            "Biceps (cm)",
            min_value=0.0,
            step=0.1,
            value=ex("biceps_cm", 0.0),
            key="entry_biceps",
        )
        chest = p4.number_input(
            "Klatka (cm)",
            min_value=0.0,
            step=0.1,
            value=ex("chest_cm", 0.0),
            key="entry_chest",
        )

        # totals
        kcal_food = kcal_m1 + kcal_m2 + kcal_m3 + kcal_add
        p_total = p_m1 + p_m2 + p_m3 + p_add
        c_total = c_m1 + c_m2 + c_m3 + c_add
        f_total = f_m1 + f_m2 + f_m3 + f_add

        kcal_steps = float(steps) * float(kcal_per_step)
        kcal_net = kcal_food - kcal_steps - float(training_kcal)

        st.markdown("### Podsumowanie")

        kcal_icon = color_for(float(kcal_food), kcal_target, kcal_target + 200)
        p_icon = macro_status(float(p_total), protein_target)
        c_icon = macro_status(float(c_total), carbs_target)
        f_icon = macro_status(float(f_total), fat_target)

        if int(steps) >= steps_target:
            s_icon = "🟢"
        elif int(steps) >= max(0, steps_target - 2000):
            s_icon = "🟡"
        else:
            s_icon = "🔴"

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Kalorie - jedzenie", f"{kcal_food:.0f}", delta=f"cel {kcal_target:.0f}")
        m2.metric("Kalorie - netto", f"{kcal_net:.0f}", delta=f"cel {kcal_target:.0f}")
        m3.metric("Białko (g)", f"{p_total:.0f}", delta=f"cel {protein_target:.0f}")
        m4.metric("Węglowodany (g)", f"{c_total:.0f}", delta=f"cel {carbs_target:.0f}")
        m5.metric("Tłuszcze (g)", f"{f_total:.0f}", delta=f"cel {fat_target:.0f}")

        st.write(
            f"**Status:** {kcal_icon} kalorie - jedzenie • {kcal_icon} kalorie - netto • "
            f"{p_icon} białko • {c_icon} węgle • {f_icon} tłuszcz • {s_icon} kroki"
        )

        btn1, btn2 = st.columns([1, 1])
        with btn1:
            save_clicked = st.button("💾 Zapisz dzień", type="primary")
        with btn2:
            clear_clicked = st.button("🧹 Wyczyść pola")

        if clear_clicked:
            st.session_state["_do_clear_form"] = True
            st.rerun()

        if save_clicked:
            # bierzemy wagę z "Pomiary ciała" jeśli wpisana, inaczej z "Aktywność"
            chosen_weight = float(weight_body) if float(weight_body) > 0 else float(weight)

            payload = dict(
                kcal_m1=float(kcal_m1),
                p_m1=float(p_m1),
                c_m1=float(c_m1),
                f_m1=float(f_m1),
                kcal_m2=float(kcal_m2),
                p_m2=float(p_m2),
                c_m2=float(c_m2),
                f_m2=float(f_m2),
                kcal_m3=float(kcal_m3),
                p_m3=float(p_m3),
                c_m3=float(c_m3),
                f_m3=float(f_m3),
                kcal_add=float(kcal_add),
                p_add=float(p_add),
                c_add=float(c_add),
                f_add=float(f_add),
                steps=int(steps),
                kcal_per_step=float(kcal_per_step),
                weight=chosen_weight if chosen_weight > 0 else None,
                training_name=training_name.strip() if training_name.strip() else None,
                training_kcal=float(training_kcal),

                # --- DODATEK: pomiary ciała ---
                waist_cm=float(waist) if float(waist) > 0 else None,
                biceps_cm=float(biceps) if float(biceps) > 0 else None,
                chest_cm=float(chest) if float(chest) > 0 else None,
            )
            with eng.begin() as conn:
                upsert_day(conn, USER_ID, d, payload)

            st.session_state["_do_clear_form"] = True
            st.success(f"Zapisano dzień {d} ✅ (formularz wyczyszczony)")
            st.rerun()

# ----------------------------
# TAB: HISTORY
# ----------------------------
with tabs[1]:
    st.subheader("Historia")
    with eng.begin() as conn:
        df = load_history(conn, USER_ID)

    if df.empty:
        st.info("Brak zapisanych dni.")
    else:
        df = df.copy()
        df["day"] = pd.to_datetime(df["day"])

        months = (
            df["day"].dt.to_period("M").astype(str).sort_values(ascending=False).unique().tolist()
        )

        if "hist_month_choice" not in st.session_state:
            st.session_state["hist_month_choice"] = "Wszystko"

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("📅 Ten miesiąc", key="hist_btn_this"):
                st.session_state["hist_month_choice"] = pd.Timestamp.today().to_period("M").astype(str)
        with b2:
            if st.button("⏮️ Poprzedni miesiąc", key="hist_btn_prev"):
                st.session_state["hist_month_choice"] = (pd.Timestamp.today().to_period("M") - 1).astype(str)
        with b3:
            if st.button("♾️ Wszystko", key="hist_btn_all"):
                st.session_state["hist_month_choice"] = "Wszystko"

        options = ["Wszystko"] + months
        chosen_month = st.selectbox(
            "Pokaż miesiąc",
            options,
            index=options.index(st.session_state["hist_month_choice"])
            if st.session_state["hist_month_choice"] in options
            else 0,
            key="hist_month_selectbox",
        )
        st.session_state["hist_month_choice"] = chosen_month

        if chosen_month != "Wszystko":
            df = df[df["day"].dt.to_period("M").astype(str) == chosen_month]

        if df.empty:
            st.info("Brak danych w wybranym miesiącu.")
        else:
            df["kcal_jedzenie"] = df["kcal_m1"] + df["kcal_m2"] + df["kcal_m3"] + df["kcal_add"]
            df["B"] = df["p_m1"] + df["p_m2"] + df["p_m3"] + df["p_add"]
            df["W"] = df["c_m1"] + df["c_m2"] + df["c_m3"] + df["c_add"]
            df["T"] = df["f_m1"] + df["f_m2"] + df["f_m3"] + df["f_add"]
            df["kcal_kroki"] = df["steps"].fillna(0) * df["kcal_per_step"].fillna(0.04)
            df["kcal_netto"] = df["kcal_jedzenie"] - df["kcal_kroki"] - df["training_kcal"].fillna(0)

            df["kcal_status"] = df["kcal_jedzenie"].apply(lambda x: color_for(float(x), kcal_target, kcal_target + 200))
            df["B_status"] = df["B"].apply(lambda x: macro_status(float(x), protein_target))
            df["W_status"] = df["W"].apply(lambda x: macro_status(float(x), carbs_target))
            df["T_status"] = df["T"].apply(lambda x: macro_status(float(x), fat_target))
            df["kroki_status"] = df["steps"].fillna(0).apply(
                lambda s: "🟢" if int(s) >= steps_target else ("🟡" if int(s) >= max(0, steps_target - 2000) else "🔴")
            )

            show = (
                df[
                    [
                        "day",
                        "steps",
                        "kcal_kroki",
                        "training_kcal",
                        "weight",
                        "kcal_jedzenie",
                        "kcal_netto",
                        "B",
                        "W",
                        "T",
                        "kcal_status",
                        "B_status",
                        "W_status",
                        "T_status",
                        "kroki_status",
                    ]
                ]
                .rename(
                    columns={
                        "day": "Data",
                        "steps": "Kroki",
                        "kcal_kroki": "kcal kroki",
                        "training_kcal": "kcal trening",
                        "weight": "Waga (kg)",
                        "kcal_jedzenie": "kcal jedzenie",
                        "kcal_netto": "kcal netto",
                        "B": "Białko (g)",
                        "W": "Węglowodany (g)",
                        "T": "Tłuszcze (g)",
                        "kcal_status": "kcal 🔥",
                        "B_status": "Białko ✅",
                        "W_status": "Węglowodany ✅",
                        "T_status": "Tłuszcze ✅",
                        "kroki_status": "Kroki 🚶",
                    }
                )
                .sort_values("Data", ascending=False)
            )

            fmt = {
                "Kroki": "{:.0f}",
                "kcal kroki": "{:.0f}",
                "kcal trening": "{:.0f}",
                "Waga (kg)": "{:.1f}",
                "kcal jedzenie": "{:.0f}",
                "kcal netto": "{:.0f}",
                "B (g)": "{:.0f}",
                "W (g)": "{:.0f}",
                "T (g)": "{:.0f}",
            }

            st.dataframe(show.style.format(fmt, na_rep=""), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.write("Usuń wybrany dzień (tylko dla zalogowanego profilu):")
            col_a, col_b = st.columns([2, 1])
            with col_a:
                dd = st.date_input(
                    "Wybierz datę do usunięcia",
                    value=show["Data"].max().date(),
                    key="hist_del_date",
                )
            with col_b:
                if st.button("🗑️ Usuń dzień", type="secondary"):
                    with eng.begin() as conn:
                        delete_day(conn, USER_ID, dd)
                    st.success(f"Usunięto {dd} ✅")
                    st.rerun()

# ----------------------------
# TAB: CHARTS
# ----------------------------
with tabs[2]:
    st.subheader("Wykresy")
    with eng.begin() as conn:
        df = load_history(conn, USER_ID)

    if df.empty:
        st.info("Brak danych do wykresów.")
    else:
        df = df.copy()
        df["day"] = pd.to_datetime(df["day"])
        df = df.sort_values("day")

        min_d = df["day"].min().date()
        max_d = df["day"].max().date()

        date_range = st.date_input(
            "Zakres na wykresach",
            value=(min_d, max_d),
            min_value=min_d,
            max_value=max_d,
            key="charts_range",
        )

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_d, end_d = date_range
        else:
            start_d, end_d = min_d, max_d

        dff = df[(df["day"].dt.date >= start_d) & (df["day"].dt.date <= end_d)].copy()

        st.markdown("### Kroki")
        steps_chart = (
            alt.Chart(dff)
            .mark_bar()
            .encode(
                x=alt.X("day:T", title="Dzień"),
                y=alt.Y("steps:Q", title="Kroki"),
                tooltip=[
                    alt.Tooltip("day:T", title="Data"),
                    alt.Tooltip("steps:Q", title="Kroki"),
                    alt.Tooltip("kcal_per_step:Q", title="kcal/krok"),
                ],
            )
            .interactive()
        )
        st.altair_chart(steps_chart, use_container_width=True)

        st.markdown("### Waga")
        wdf = dff.dropna(subset=["weight"]).sort_values("day")
        if wdf.empty:
            st.info("Brak wagi w danych w wybranym zakresie.")
        else:
            weight_chart = (
                alt.Chart(wdf)
                .mark_line(point=True)
                .encode(
                    x=alt.X("day:T", title="Dzień"),
                    y=alt.Y("weight:Q", title="Waga (kg)"),
                    tooltip=[
                        alt.Tooltip("day:T", title="Data"),
                        alt.Tooltip("weight:Q", title="Waga (kg)", format=".1f"),
                        alt.Tooltip("steps:Q", title="Kroki"),
                    ],
                )
                .interactive()
            )
            st.altair_chart(weight_chart, use_container_width=True)

            delta_kg = float(wdf["weight"].iloc[-1]) - float(wdf["weight"].iloc[0])
            st.metric("Zmiana wagi od pierwszego pomiaru (w zakresie)", f"{delta_kg:+.1f} kg")

        # --- DODATEK: WYKRES POMIARÓW CIAŁA (wybieralne serie) ---
        st.markdown("### Pomiary ciała (wybierz co ma być widoczne)")
        options = {
            "Waga (kg)": "weight",
            "Talia (cm)": "waist_cm",
            "Biceps (cm)": "biceps_cm",
            "Klatka (cm)": "chest_cm",
        }
        chosen = st.multiselect(
            "Serie na wykresie",
            list(options.keys()),
            default=["Talia (cm)", "Biceps (cm)", "Klatka (cm)"],
            key="meas_series",
        )

        if not chosen:
            st.info("Wybierz przynajmniej jedną serię.")
        else:
            cols = ["day"] + [options[k] for k in chosen]
            mdf = dff[cols].copy()

            # wywalamy wiersze gdzie wszystkie wybrane wartości są puste
            val_cols = [options[k] for k in chosen]
            mdf = mdf.dropna(subset=val_cols, how="all")

            if mdf.empty:
                st.info("Brak danych pomiarów w wybranym zakresie.")
            else:
                long = mdf.melt(id_vars=["day"], value_vars=val_cols, var_name="metric", value_name="value")
                # mapka nazw ładnych do legendy
                inv = {v: k for k, v in options.items()}
                long["metric"] = long["metric"].map(inv)

                meas_chart = (
                    alt.Chart(long.dropna(subset=["value"]))
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("day:T", title="Dzień"),
                        y=alt.Y("value:Q", title="Wartość"),
                        color=alt.Color("metric:N", title="Pomiar"),
                        tooltip=[
                            alt.Tooltip("day:T", title="Data"),
                            alt.Tooltip("metric:N", title="Pomiar"),
                            alt.Tooltip("value:Q", title="Wartość", format=".1f"),
                        ],
                    )
                    .interactive()
                )
                st.altair_chart(meas_chart, use_container_width=True)

# ----------------------------
# TAB: SETTINGS
# ----------------------------
with tabs[3]:
    st.subheader("Cele / Ustawienia")
    st.write("Zmieniasz cele i progi kolorów dla zalogowanego profilu.")

    c1, c2, c3, c4, c5 = st.columns(5)
    new_kcal = c1.number_input("Cel kcal", min_value=500.0, step=50.0, value=float(kcal_target), key="set_kcal")
    new_p = c2.number_input("Cel B (g)", min_value=0.0, step=5.0, value=float(protein_target), key="set_p")
    new_c = c3.number_input("Cel W (g)", min_value=0.0, step=5.0, value=float(carbs_target), key="set_c")
    new_f = c4.number_input("Cel T (g)", min_value=0.0, step=5.0, value=float(fat_target), key="set_f")
    new_steps = c5.number_input("Cel kroków", min_value=0, step=500, value=int(steps_target), key="set_steps")

    st.caption("Kcal: 🟢 do celu • 🟡 cel+200 • 🔴 powyżej. Kroki: 🟢 >= cel • 🟡 >= cel-2000 • 🔴 mniej.")

    if st.button("💾 Zapisz ustawienia", type="primary"):
        with eng.begin() as conn:
            set_setting(conn, USER_ID, "kcal_target", str(float(new_kcal)))
            set_setting(conn, USER_ID, "protein_target", str(float(new_p)))
            set_setting(conn, USER_ID, "carbs_target", str(float(new_c)))
            set_setting(conn, USER_ID, "fat_target", str(float(new_f)))
            set_setting(conn, USER_ID, "steps_target", str(int(new_steps)))

        st.success("Zapisano ustawienia ✅")
        st.rerun()
