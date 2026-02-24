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

USERS = {
    "Kacper": {"pin": "1111", "user_id": 1},
    "Klaudia": {"pin": "2222", "user_id": 2},
}

# ----------------------------
# DB
# ----------------------------
def get_database_url():
    if "DATABASE_URL" in st.secrets:
        return st.secrets["DATABASE_URL"]
    return os.environ.get("DATABASE_URL")

@st.cache_resource
def get_engine():
    return create_engine(
        get_database_url(),
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args={"options": "-csearch_path=public"},
    )

def ensure_schema():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            create table if not exists public.settings (
                user_id bigint not null,
                key text not null,
                value text not null,
                updated_at timestamptz default now(),
                primary key (user_id, key)
            );
        """))

        conn.execute(text("""
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

                waist_cm numeric,
                biceps_cm numeric,
                chest_cm numeric,

                updated_at timestamptz default now(),
                primary key (user_id, day)
            );
        """))

def get_setting(conn, user_id, key, default):
    row = conn.execute(
        text("select value from public.settings where user_id=:uid and key=:k"),
        {"uid": user_id, "k": key},
    ).mappings().first()
    return row["value"] if row else default

def set_setting(conn, user_id, key, value):
    conn.execute(text("""
        insert into public.settings (user_id, key, value, updated_at)
        values (:uid, :k, :v, now())
        on conflict (user_id, key)
        do update set value = excluded.value, updated_at = now()
    """), {"uid": user_id, "k": key, "v": value})

def upsert_day(conn, user_id, d, payload):
    payload = {**payload, "user_id": user_id, "day": d}
    conn.execute(text("""
        insert into public.daily (
            user_id, day,
            kcal_m1,p_m1,c_m1,f_m1,
            kcal_m2,p_m2,c_m2,f_m2,
            kcal_m3,p_m3,c_m3,f_m3,
            kcal_add,p_add,c_add,f_add,
            steps,kcal_per_step,weight,
            training_name,training_kcal,
            waist_cm,biceps_cm,chest_cm,
            updated_at
        ) values (
            :user_id,:day,
            :kcal_m1,:p_m1,:c_m1,:f_m1,
            :kcal_m2,:p_m2,:c_m2,:f_m2,
            :kcal_m3,:p_m3,:c_m3,:f_m3,
            :kcal_add,:p_add,:c_add,:f_add,
            :steps,:kcal_per_step,:weight,
            :training_name,:training_kcal,
            :waist_cm,:biceps_cm,:chest_cm,
            now()
        )
        on conflict (user_id, day)
        do update set
            kcal_m1=excluded.kcal_m1,
            p_m1=excluded.p_m1,
            c_m1=excluded.c_m1,
            f_m1=excluded.f_m1,
            kcal_m2=excluded.kcal_m2,
            p_m2=excluded.p_m2,
            c_m2=excluded.c_m2,
            f_m2=excluded.f_m2,
            kcal_m3=excluded.kcal_m3,
            p_m3=excluded.p_m3,
            c_m3=excluded.c_m3,
            f_m3=excluded.f_m3,
            kcal_add=excluded.kcal_add,
            p_add=excluded.p_add,
            c_add=excluded.c_add,
            f_add=excluded.f_add,
            steps=excluded.steps,
            kcal_per_step=excluded.kcal_per_step,
            weight=excluded.weight,
            training_name=excluded.training_name,
            training_kcal=excluded.training_kcal,
            waist_cm=excluded.waist_cm,
            biceps_cm=excluded.biceps_cm,
            chest_cm=excluded.chest_cm,
            updated_at=now()
    """), payload)

def load_history(conn, user_id):
    df = pd.read_sql(
        text("select * from public.daily where user_id=:uid order by day desc"),
        conn,
        params={"uid": user_id},
    )
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df

# ----------------------------
# FORM RESET
# ----------------------------
def fv_key(base):
    v = st.session_state.get("form_version", 0)
    return f"{base}_{v}"

ensure_schema()

if "form_version" not in st.session_state:
    st.session_state["form_version"] = 0

# ----------------------------
# LOGIN
# ----------------------------
if "user_id" not in st.session_state:
    st.title("🍽️ Fit Tracker")
    user = st.selectbox("Profil", list(USERS.keys()))
    pin = st.text_input("PIN", type="password")
    if st.button("Zaloguj"):
        if pin == USERS[user]["pin"]:
            st.session_state["user_id"] = USERS[user]["user_id"]
            st.session_state["user_name"] = user
            st.session_state["form_version"] += 1
            st.rerun()
        else:
            st.error("Zły PIN")
    st.stop()

USER_ID = st.session_state["user_id"]
USER_NAME = st.session_state["user_name"]

st.title("🍽️ Fit Tracker")
st.success(f"Zalogowany: {USER_NAME}")

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

tabs = st.tabs(["Wpis", "Historia", "Wykresy"])

# ----------------------------
# WPIS (zawsze 0)
# ----------------------------
with tabs[0]:

    d = st.date_input("Data", value=date.today(), key=fv_key("date"))

    def ni(label, step=1.0):
        return st.number_input(label, min_value=0.0, step=step, value=0.0, key=fv_key(label))

    st.subheader("Posiłki")
    kcal_m1 = ni("kcal m1")
    p_m1 = ni("B m1", 0.1)
    c_m1 = ni("W m1", 0.1)
    f_m1 = ni("T m1", 0.1)

    st.subheader("Aktywność")
    steps = st.number_input("Kroki", min_value=0, step=100, value=0, key=fv_key("steps"))
    kcal_per_step = st.number_input("kcal/krok", min_value=0.0, step=0.01, value=0.04, key=fv_key("kps"))

    st.subheader("Pomiary")
    weight = ni("Waga", 0.1)
    waist = ni("Talia", 0.1)
    biceps = ni("Biceps", 0.1)
    chest = ni("Klatka", 0.1)

    if st.button("💾 Zapisz dzień"):
        with eng.begin() as conn:
            upsert_day(conn, USER_ID, d, dict(
                kcal_m1=kcal_m1,p_m1=p_m1,c_m1=c_m1,f_m1=f_m1,
                kcal_m2=0,p_m2=0,c_m2=0,f_m2=0,
                kcal_m3=0,p_m3=0,c_m3=0,f_m3=0,
                kcal_add=0,p_add=0,c_add=0,f_add=0,
                steps=steps,kcal_per_step=kcal_per_step,
                weight=weight if weight>0 else None,
                training_name=None,training_kcal=0,
                waist_cm=waist if waist>0 else None,
                biceps_cm=biceps if biceps>0 else None,
                chest_cm=chest if chest>0 else None,
            ))
        st.session_state["form_version"] += 1
        st.success("Zapisano i wyczyszczono formularz")
        st.rerun()

    if st.button("🧹 Wyczyść pola"):
        st.session_state["form_version"] += 1
        st.rerun()

# ----------------------------
# HISTORIA
# ----------------------------
with tabs[1]:
    with eng.begin() as conn:
        df = load_history(conn, USER_ID)

    if df.empty:
        st.info("Brak danych")
    else:
        st.dataframe(df, use_container_width=True)

# ----------------------------
# WYKRESY
# ----------------------------
with tabs[2]:
    with eng.begin() as conn:
        df = load_history(conn, USER_ID)

    if df.empty:
        st.info("Brak danych")
    else:
        df["day"] = pd.to_datetime(df["day"])
        chart = alt.Chart(df).mark_line(point=True).encode(
            x="day:T",
            y="weight:Q"
        )
        st.altair_chart(chart, use_container_width=True)
