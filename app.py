import unicodedata
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
import yaml
import folium
from streamlit_folium import st_folium

from src.climate_tx import extract_historical_tx_series, generate_serie_tx_and_tpa
from src.excel_builder import build_excel_report
from src.spatial_ageb import compute_prioridad_sombra
from src.pdf_builder import build_executive_pdf

st.set_page_config(page_title="IUA México", layout="wide")

plt.rcParams["font.sans-serif"] = ["Plus Jakarta Sans", "DejaVu Sans", "Arial"]
plt.rcParams["axes.edgecolor"] = "#CBD5E1"
plt.rcParams["axes.linewidth"] = 0.8

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        html, body, .stApp, h1, h2, h3, h4, p, label, button, input, select,
        [data-baseweb="select"] div, [data-baseweb="select"] span,
        [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
            font-family: 'Plus Jakarta Sans', sans-serif !important;
        }

        [data-testid="stSidebarCollapseButton"] span,
        [data-testid="stExpander"] summary svg {
            font-family: 'Material Symbols Rounded' !important;
            color: #FFFFFF !important;
        }

        .stApp {
            background-color: #FFFFFF;
            color: #0B3C49;
        }

        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div:first-child,
        [data-testid="stSidebarContent"] {
            background-color: #0B3C49 !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p {
            color: #FFFFFF !important;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] {
            background-color: rgba(255, 255, 255, 0.06) !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
            border-radius: 8px !important;
            margin-top: 12px !important;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary p {
            font-size: 14.5px !important;
            font-weight: 600 !important;
            color: #FFFFFF !important;
        }

        h1 {
            color: #0B3C49 !important;
            font-size: 32px !important;
            font-weight: 700 !important;
        }
        h2, h3 {
            color: #0B3C49 !important;
            font-size: 21px !important;
            font-weight: 600 !important;
        }

        p, label {
            font-size: 15.5px !important;
            color: #1A202C;
        }

        [data-baseweb="select"] div,
        [data-baseweb="select"] span,
        [data-baseweb="input"] input {
            font-size: 15px !important;
        }

        [data-testid="stSidebar"] [role="slider"] {
            background-color: #FFFFFF !important;
        }
        [data-testid="stSidebar"] [data-baseweb="slider"] > div > div > div {
            background-color: #FFFFFF !important;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            margin-top: 22px !important;
            margin-bottom: 12px !important;
            padding-bottom: 6px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:first-child h1,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:first-child h2,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:first-child h3 {
            margin-top: 0px !important;
        }

        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] div {
            font-size: 34px !important;
            color: #0B3C49 !important;
            font-weight: 800 !important;
            line-height: 1.15 !important;
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] p {
            font-size: 14.5px !important;
            color: #4A5568 !important;
            font-weight: 600 !important;
        }

        .banner-urgencia {
            background-color: #E6F2F5;
            border-left: 5px solid #0B3C49;
            color: #0B3C49;
            padding: 18px 22px;
            border-radius: 10px;
            font-size: 15.5px;
            line-height: 1.55;
            margin-bottom: 14px;
        }

        .banner-demo {
            background-color: #FEF3C7;
            border-left: 5px solid #D97706;
            color: #92400E;
            padding: 14px 20px;
            border-radius: 8px;
            font-size: 14.5px;
            font-weight: 600;
            margin-bottom: 14px;
        }

        .card-petroleo {
            background-color: #E6F2F5;
            border-left: 5px solid #0B3C49;
            padding: 18px;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(11, 60, 73, 0.06);
            margin-bottom: 26px;
            font-size: 15px;
            line-height: 1.55;
            color: #0B3C49;
            min-height: 110px;
        }

        .stButton>button, .stDownloadButton>button {
            background-color: #0B3C49 !important;
            border-radius: 8px !important;
            padding: 0.55rem 1.4rem !important;
            border: none !important;
            min-height: 44px !important;
        }
        .stButton>button p, .stDownloadButton>button p,
        .stButton>button span, .stDownloadButton>button span {
            color: #FFFFFF !important;
            font-weight: 600 !important;
            font-size: 16px !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .stButton>button:hover, .stDownloadButton>button:hover {
            background-color: #072932 !important;
        }
    </style>
""", unsafe_allow_html=True)

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


def _norm_str(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s).strip().lower())
        if unicodedata.category(c) != "Mn"
    )


@st.cache_data
def load_municipios():
    gdf = gpd.read_file("data/raw/sig/municipios_mexico.geojson")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf_metric = gdf.to_crs(epsg=6372)
    gdf["area_km2"] = gdf_metric.geometry.area / 1e6
    return gdf


def get_municipal_defaults(estado: str, area_km2: float) -> dict:
    norte_arido = {
        "baja california", "baja california sur", "sonora", "chihuahua",
        "coahuila", "nuevo leon", "tamaulipas", "durango", "zacatecas", "san luis potosi"
    }
    sur_humedo = {
        "tabasco", "chiapas", "campeche", "yucatan", "quintana roo",
        "veracruz", "oaxaca", "guerrero", "colima", "nayarit", "sinaloa"
    }
    est_norm = _norm_str(estado)
    factor_escala = 1.5 if area_km2 > 800 else (0.5 if area_km2 > 250 else 0.0)

    if est_norm in norte_arido:
        return {"meta_copa": 20, "tau_arb": 9.5, "tau_cor": round(10.0 + factor_escala, 1), "tau_ban": round(6.0 + factor_escala * 0.5, 1)}
    elif est_norm in sur_humedo:
        return {"meta_copa": 30, "tau_arb": 7.0, "tau_cor": round(9.0 + factor_escala, 1), "tau_ban": round(5.5 + factor_escala * 0.5, 1)}
    else:
        return {"meta_copa": 28, "tau_arb": 8.5, "tau_cor": round(9.5 + factor_escala, 1), "tau_ban": round(6.0 + factor_escala * 0.5, 1)}


def compute_theil_sen_trend(x: np.ndarray, y: np.ndarray):
    """Calcula la pendiente no paramétrica de Theil-Sen (días/año) e intercepto."""
    n = len(x)
    slopes = [
        (y[j] - y[i]) / (x[j] - x[i])
        for i in range(n)
        for j in range(i + 1, n)
        if x[j] != x[i]
    ]
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def plot_ipcc_plume(df_tx: pd.DataFrame, limite_dias: float, tse_reg, umbral_c: float, municipio: str):
    fig, ax = plt.subplots(figsize=(10.5, 4.3), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    hist = df_tx[df_tx["Ref_historica"].notna()]
    proj = df_tx[df_tx["SSP5-8.5 P50 (mediana)"].notna()]

    ax.plot(hist["Año"], hist["Ref_historica"], color="#475569", linewidth=1.6, label="Registro histórico (ERA5 / Open-Meteo)")
    ax.plot(proj["Año"], proj["SSP2-4.5 P50 (mediana)"], color="#2B6CB0", linewidth=2.2, linestyle="--", label="Trayectoria intermedia SSP2-4.5 (P50)")
    ax.plot(proj["Año"], proj["SSP5-8.5 P50 (mediana)"], color="#0B3C49", linewidth=2.6, label="Trayectoria altas emisiones SSP5-8.5 (P50)")
    ax.fill_between(
        proj["Año"],
        proj["SSP5-8.5 P50 (mediana)"],
        proj["SSP5-8.5 P90"],
        color="#0B3C49",
        alpha=0.14,
        label="Rango superior SSP5-8.5 (P50 – P90)"
    )

    ax.axhline(limite_dias, color="#9B2C2C", linestyle=":", linewidth=1.6, label=f"Máximo referencia 1981–2010 ({limite_dias:.0f} días/año)")

    tse_num = None
    if tse_reg is not None and pd.notna(tse_reg):
        try:
            tse_num = float(tse_reg)
        except (TypeError, ValueError):
            tse_num = None

    if tse_num is not None and 2026 <= tse_num <= 2100:
        ax.axvline(tse_num, color="#9B2C2C", linestyle="-.", linewidth=1.4, alpha=0.85)
        ax.text(
            tse_num + 1.5,
            limite_dias + 22,
            f"TsE Regional\n(≈ {int(round(tse_num))})",
            color="#9B2C2C",
            fontsize=9.0,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="none", alpha=0.88),
        )

    ax.set_title(f"Proyección Emulada de Días con Temperatura Máxima > {umbral_c} °C — {municipio}", fontsize=12.5, fontweight="bold", color="#0B3C49", pad=14, loc="left")
    ax.set_xlabel("Año (1950–2100)", fontsize=10.5, fontweight="bold", color="#1E293B", labelpad=8)
    ax.set_ylabel("Frecuencia anual (días / año)", fontsize=10.5, fontweight="bold", color="#1E293B", labelpad=8)
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", linewidth=0.5, color="#E2E8F0", alpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors="#334155", labelsize=9.5)
    ax.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", fontsize=8.8, ncol=2)

    plt.tight_layout()
    return fig


def plot_climate_index_bars(df_hist: pd.DataFrame, col_name: str, titulo: str, ylabel: str, color_bar: str, color_trend: str):
    """Gráfica estándar OMM/ETCCDI: barras anuales + media móvil 10 años + tendencia Theil-Sen."""
    fig, ax = plt.subplots(figsize=(6.2, 3.9), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    anios = df_hist["Anio"].to_numpy(dtype=float)
    valores = df_hist[col_name].to_numpy(dtype=float)

    media_movil = pd.Series(valores).rolling(window=10, min_periods=10).mean()
    slope_yr, intercept = compute_theil_sen_trend(anios, valores)
    tendencia_sen = intercept + slope_yr * anios
    slope_dec = slope_yr * 10.0

    ax.bar(anios, valores, color=color_bar, alpha=0.35, width=0.75, label="Registro anual (ERA5 / Open-Meteo)")
    ax.plot(anios, media_movil, color="#475569", linewidth=1.8, linestyle="--", label="Media móvil (10 años)")
    ax.plot(
        anios,
        tendencia_sen,
        color=color_trend,
        linewidth=2.3,
        label=f"Tendencia Theil-Sen ({slope_dec:+.2f} días/década)"
    )

    ax.set_title(titulo, fontsize=11.5, fontweight="bold", color="#0B3C49", pad=12, loc="left")
    ax.set_xlabel("Año (1950–2024)", fontsize=10, fontweight="bold", color="#1E293B", labelpad=6)
    ax.set_ylabel(ylabel, fontsize=10, fontweight="bold", color="#1E293B", labelpad=6)
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, color="#E2E8F0")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors="#334155", labelsize=9)
    ax.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0", fontsize=8.3)

    plt.tight_layout()
    return fig


gdf_mun = load_municipios()
anio_base_cfg = int(cfg.get("proyecto", {}).get("anio_base", 2026))

st.sidebar.header("Localidad")
estados = sorted(gdf_mun["ESTADO"].unique())
idx_nl = estados.index("Nuevo León") if "Nuevo León" in estados else 0
estado_sel = st.sidebar.selectbox("Estado", estados, index=idx_nl)

sub_mun = gdf_mun[gdf_mun["ESTADO"] == estado_sel].sort_values("MUNICIPIO")
muns = sub_mun["MUNICIPIO"].tolist()
idx_mty = muns.index("Monterrey") if "Monterrey" in muns else 0
mun_sel = st.sidebar.selectbox("Municipio", muns, index=idx_mty)

row_sel = sub_mun[sub_mun["MUNICIPIO"] == mun_sel].iloc[0]
defs = get_municipal_defaults(estado_sel, float(row_sel["area_km2"]))
mun_key = f"{estado_sel}_{mun_sel}"

umbral_opcion = st.sidebar.selectbox(
    "Umbral de calor extremo",
    [
        "Percentil 95 local (TX95p — recomendado)",
        "TX30 (Tmáx > 30 °C — clima templado)",
        "TX35 (Tmáx > 35 °C — cálido)",
        "TX40 (Tmáx > 40 °C — extremo)",
    ],
    index=0,
    key=f"umb_{mun_key}",
)
usar_p95 = "Percentil 95" in umbral_opcion
umbral_tx = 30.0 if "TX30" in umbral_opcion else (40.0 if "TX40" in umbral_opcion else 35.0)

busqueda_colonia = st.sidebar.text_input("Código Postal, Colonia o AGEB (opcional)", "", placeholder="Ej. 64000 o Mitras")

st.sidebar.header("Meta de cobertura")
meta_copa = st.sidebar.slider("Meta mínima de copa por AGEB (%)", 10, 45, defs["meta_copa"], key=f"copa_{mun_key}")
perfil_pesos = st.sidebar.selectbox(
    "Criterio de priorización territorial",
    [
        "Equilibrado (45% Copa / 35% Calor / 20% Social)",
        "Prioridad Social (35% Copa / 25% Calor / 40% Social)",
        "Islas de Calor (35% Copa / 50% Calor / 15% Social)",
    ],
    key=f"ips_{mun_key}",
)
pesos = (0.35, 0.25, 0.40) if "Social" in perfil_pesos else ((0.35, 0.50, 0.15) if "Islas" in perfil_pesos else (0.45, 0.35, 0.20))

with st.sidebar.expander("Tiempo de consolidación vegetal — τ (años)", expanded=False):
    st.caption("Supuesto editable de establecimiento a copa funcional (referencia silvicultura urbana: 7–12 años).")
    tau_arb = st.slider("Arbolado de alineación", 4.0, 15.0, defs["tau_arb"], 0.5, key=f"tarb_{mun_key}")
    tau_cor = st.slider("Infraestructura verde lineal", 5.0, 20.0, defs["tau_cor"], 0.5, key=f"tcor_{mun_key}")
    tau_ban = st.slider("Cruces y banquetas peatonales", 2.0, 12.0, defs["tau_ban"], 0.5, key=f"tban_{mun_key}")

with st.sidebar.expander("Gobernanza de Datos", expanded=False):
    modo_demo = st.toggle(
        "Modo demostración (cifras ilustrativas)",
        value=False,
        help="En modo estricto (apagado), el sistema bloquea la emisión de reportes si falta algún insumo real. Active este modo solo para demostraciones con cifras ilustrativas.",
    )

st.sidebar.markdown("---")
st.sidebar.caption(
    "**Autoría y Soporte Técnico**  \n"
    "Baruc Martínez Velasco  \n"
    "**Contacto:** `martinezbaruc13@gmail.com`"
)

st.title("Índice de Urgencia Adaptativa en México")
st.caption("Diagnóstico municipal de calor extremo, prioridad de arborización, estrés térmico húmedo e infraestructura azul-verde")

if st.button("Diagnóstico Municipal", type="primary"):
    mun_id = f"{estado_sel}_{mun_sel}".replace(" ", "_").lower()
    strict_mode = not modo_demo

    with st.spinner("Consultando satélites (WorldCover/Landsat), clima (ERA5/CMIP6) y red vial..."):
        try:
            gdf_ageb, gdf_streets, micro = compute_prioridad_sombra(
                row_sel.geometry, mun_id, cfg, meta_copa=meta_copa, pesos=pesos
            )
            df_hist, climate_flags = extract_historical_tx_series(
                "data/raw/era5",
                row_sel.geometry,
                umbral_tx=umbral_tx,
                usar_p95=usar_p95,
                strict_mode=strict_mode,
            )
            umbral_real = climate_flags["umbral_efectivo_C"]
            df_tx, df_tpa, limite_dias, cmip6_real = generate_serie_tx_and_tpa(
                row_sel.geometry,
                df_hist,
                delta_icu_c=micro["delta_icu_aire_c"],
                anio_base=anio_base_cfg,
                umbral_tx=umbral_real,
                tau_consolidacion=tau_arb,
                strict_mode=strict_mode,
                ref_daily_tmax=climate_flags.get("ref_daily_tmax"),
            )

            st.session_state["res"] = {
                "estado": estado_sel,
                "mun": mun_sel,
                "poly": row_sel.geometry,
                "gdf_ageb": gdf_ageb,
                "gdf_streets": gdf_streets,
                "micro": micro,
                "df_hist": df_hist,
                "flags": climate_flags,
                "cmip6_real": cmip6_real,
                "df_tx": df_tx,
                "df_tpa": df_tpa,
                "limite": limite_dias,
                "umbral": umbral_real,
                "taus": (tau_arb, tau_cor, tau_ban),
                "meta_copa": meta_copa,
                "modo_demo": bool(modo_demo),
            }
        except (RuntimeError, ValueError) as err:
            st.error(f"BLOQUEO POR GOBERNANZA DE DATOS (Modo Estricto): {err}")

if "res" in st.session_state:
    res = st.session_state["res"]
    gdf_ageb_eval = res["gdf_ageb"].copy()
    gdf_streets = res["gdf_streets"]
    micro_eval = dict(res["micro"])
    df_hist = res["df_hist"]
    df_tx = res["df_tx"]
    df_tpa = res["df_tpa"]
    tau_arb, tau_cor, tau_ban = res["taus"]

    # Congelar el modo de demostración tal como estaba al momento de ejecutar el diagnóstico
    en_demo = bool(res.get("modo_demo", False))
    n_escenas_lst = int(micro_eval.get("lst_escenas_compuesto", 0))
    lst_normativo_ok = bool(micro_eval.get("lst_real", False) and n_escenas_lst >= 3)

    respaldos = []
    if not micro_eval.get("wc_real", True):
        respaldos.append("Cobertura arbórea (WorldCover)")
    if not lst_normativo_ok:
        if n_escenas_lst > 0:
            respaldos.append(f"Temperatura superficial Landsat (<3 escenas válidas: {n_escenas_lst})")
        else:
            respaldos.append("Temperatura superficial (Landsat sin escenas válidas)")
    if not res["flags"].get("era5_real", True):
        respaldos.append("Clima histórico (ERA5 / Open-Meteo)")
    if not res.get("cmip6_real", True):
        respaldos.append("Proyecciones (CMIP6)")

    sin_conapo = ("Marginacion_idx" not in gdf_ageb_eval.columns) or gdf_ageb_eval["Marginacion_idx"].isna().all()
    bloquear_pdf = bool(respaldos) and not en_demo

    if en_demo:
        st.markdown(
            '<div class="banner-demo">VISTA DE DEMOSTRACIÓN — CIFRAS ILUSTRATIVAS NO VÁLIDAS PARA USO NORMATIVO O DICTAMEN DE OBRA PÚBLICA.</div>',
            unsafe_allow_html=True,
        )
    elif respaldos:
        st.error(
            f"BLOQUEO NORMATIVO ACTIVO — Faltan insumos reales verificados en: {', '.join(respaldos)}. "
            "La emisión de la Ficha Ejecutiva PDF institucional está bloqueada hasta incorporar los insumos locales o recalcular en Modo Demostración."
        )

    if bool(modo_demo) != en_demo:
        st.info("Cambiaste el interruptor de Modo Demostración después de calcular. Presiona «Diagnóstico Municipal» para recalcular bajo el nuevo modo.")

    med_ssp5 = df_tpa[(df_tpa["Escenario"] == "SSP5-8.5") & (df_tpa["Percentil"].str.contains("P50"))].iloc[0]

    tpa_reg = med_ssp5["TpA_anios"]
    tse_reg = med_ssp5["TSE_regional"]
    tpa_icu = med_ssp5["TpA_con_ICU"]
    tse_icu = med_ssp5["TSE_con_ICU"]
    horizonte_med = med_ssp5.get("Horizonte", "Dentro de horizonte 2100")

    valid_tpas = df_tpa["TpA_anios"].dropna()
    valid_tpas = valid_tpas[valid_tpas > 0]
    if not valid_tpas.empty:
        iua_min = round(tau_arb / float(valid_tpas.max()), 2)
        iua_max = round(tau_arb / float(valid_tpas.min()), 2)
        rango_txt = f" | rango multi-escenario CMIP6: {iua_min} – {iua_max}"
    else:
        rango_txt = ""

    horizonte_max_cota = max(2100 - anio_base_cfg, 1)
    iua_cota_2100 = round(tau_arb / float(horizonte_max_cota), 2)

    if pd.isna(tpa_reg) or ">2100" in str(horizonte_med):
        nivel_urgencia = "Baja (>2100)"
        iua_label = f"< {iua_cota_2100:.2f} (>2100)"
        tse_reg_txt = ">2100"
        tpa_reg_txt = f">{horizonte_max_cota} años"
        texto_urgencia = (
            f"<b>HORIZONTE POSTERIOR A 2100 (IUA < {iua_cota_2100:.2f}):</b> Bajo la mediana SSP5-8.5 regional, la media móvil de 20 años no rebasa "
            f"el máximo histórico de referencia dentro del siglo XXI (<b>TsE > 2100</b>). Con ajuste urbano estimado por Isla de Calor "
            f"(<b>+ΔICU ≈ {micro_eval['delta_icu_aire_c']} °C</b>), el horizonte de sensibilidad se ubica en <b>{int(tse_icu) if pd.notna(tse_icu) else '>2100'}</b>."
        )
    elif float(tpa_reg) <= 0:
        nivel_urgencia = "REBASADO"
        iua_label = "Rebasado"
        tse_reg_txt = f"{int(round(tse_reg))}"
        tpa_reg_txt = "Rebasado"
        texto_urgencia = (
            f"<b>HORIZONTE REBASADO (TsE Regional ≈ {tse_reg_txt}):</b> La climatología observada ya superó el máximo histórico de referencia "
            f"antes del año base ({anio_base_cfg}). Se requiere implementación inmediata de refugios climáticos y arborización intensiva (<b>τ = {tau_arb} años</b>)."
        )
    else:
        iua_arb = round(tau_arb / float(tpa_reg), 2)
        iua_label = f"{iua_arb:.2f}"
        tse_reg_txt = f"{int(round(tse_reg))}"
        tpa_reg_txt = f"{tpa_reg:.1f} años"
        tse_icu_txt = f"≈ {int(round(tse_icu))}" if pd.notna(tse_icu) else ">2100"

        if iua_arb >= 1.0:
            nivel_urgencia = "Crítica"
            texto_urgencia = (
                f"<b>URGENCIA CRÍTICA (IUA Regional = {iua_arb:.2f}{rango_txt}):</b> La ventana regional antes de superar el máximo histórico de referencia "
                f"(<b>TsE ≈ {tse_reg_txt}</b>, en <b>{tpa_reg:.1f} años</b>; sensibilidad urbana con ΔICU: <b>TsE {tse_icu_txt}</b>) es <b>menor o igual</b> al tiempo de consolidación vegetal "
                f"(<b>τ = {tau_arb} años</b>). Se requiere intervención inmediata en las AGEB del Quintil Superior."
            )
        elif iua_arb >= 0.7:
            nivel_urgencia = "Alta"
            texto_urgencia = (
                f"<b>URGENCIA ALTA (IUA Regional = {iua_arb:.2f}{rango_txt}):</b> Quedan <b>{tpa_reg:.1f} años</b> antes de alcanzar el Tiempo sin Precedentes regional "
                f"(<b>TsE ≈ {tse_reg_txt}</b>; sensibilidad urbana con ΔICU: <b>TsE {tse_icu_txt}</b>), margen estrecho frente a los <b>{tau_arb} años</b> de consolidación."
            )
        else:
            nivel_urgencia = "Moderada"
            texto_urgencia = (
                f"<b>URGENCIA MODERADA / VENTANA ABIERTA (IUA Regional = {iua_arb:.2f}{rango_txt}):</b> El municipio dispone de <b>{tpa_reg:.1f} años</b> antes de alcanzar "
                f"<b>TsE ≈ {tse_reg_txt}</b> (sensibilidad urbana con ΔICU: <b>TsE {tse_icu_txt}</b>), margen suficiente para ejecutar el plan de arborización (<b>τ = {tau_arb} años</b>)."
            )

    tse_reg_plot = tse_reg
    tse_reg_pdf = tse_reg if pd.notna(tse_reg) else ">2100"
    iua_pdf_str = f"{iua_label} — Urgencia {nivel_urgencia}"

    # === FILTRO HÍBRIDO: CLIMA TEMPLADO REGIONAL VS. ISLA DE CALOR POR AGEB ===
    ult_10_pdf = df_hist[df_hist["Anio"] >= 2015]
    wbt_max_rec = float(ult_10_pdf["WBT_max_anual"].max()) if not ult_10_pdf.empty else 25.0
    cobertura_mun = float(micro_eval.get("copa_media_pct", 0.0))
    es_conservacion = False

    if wbt_max_rec < 26.5 and "LST_verano_C" in gdf_ageb_eval.columns:
        lst_s = gdf_ageb_eval["LST_verano_C"].fillna(26.0)
        copa_s = gdf_ageb_eval["Copa_pct"].fillna(cobertura_mun)

        sin_estres_ageb = (lst_s < 30.0) & ~((lst_s >= 28.0) & (copa_s < res["meta_copa"]))

        gdf_ageb_eval.loc[sin_estres_ageb, "Prioridad"] = "Conservación (Clima templado)"
        gdf_ageb_eval.loc[sin_estres_ageb, "Arboles_equivalentes"] = 0
        gdf_ageb_eval.loc[sin_estres_ageb, "Brecha_copa_ha"] = 0.0

        arb_restantes = int(gdf_ageb_eval["Arboles_equivalentes"].sum())
        ha_restantes = round(float(gdf_ageb_eval["Brecha_copa_ha"].sum()), 2)
        micro_eval["arboles_totales"] = arb_restantes
        micro_eval["brecha_total_ha"] = ha_restantes

        if arb_restantes == 0:
            es_conservacion = True
            lst_mediana_mun = float(lst_s.median())
            nivel_urgencia = "Conservación (Clima templado)"
            iua_label = "0.00 (No aplica)"
            iua_pdf_str = "0.00 — Conservación (Sin estrés térmico crítico)"
            tse_reg_txt = "No aplica"
            tpa_reg_txt = "Clima Templado"
            tse_icu = None
            tpa_reg = None
            tse_reg_plot = None
            tse_reg_pdf = "No aplica"
            texto_urgencia = (
                f"<b>ZONA DE CONSERVACIÓN / CLIMA TEMPLADO:</b> El municipio registra una temperatura superficial estival mediana de "
                f"<b>{lst_mediana_mun:.1f} °C</b>, bulbo húmedo máximo reciente de <b>{wbt_max_rec:.1f} °C</b> "
                f"y una cobertura arbórea del <b>{cobertura_mun:.1f}%</b>. Ninguna unidad urbana presenta isla de calor severa; "
                f"la estrategia prioritaria es la <b>conservación ambiental y manejo forestal sustentable</b>."
            )
        else:
            n_ageb_calor = int((~sin_estres_ageb).sum())
            nivel_urgencia = "Focalizada (Clima templado + ICU local)"
            iua_pdf_str = f"{iua_label} — Gestión de Isla de Calor Local"
            texto_urgencia = (
                f"<b>CLIMA TEMPLADO CON ISLAS DE CALOR INTRAURBANAS:</b> A escala regional no existe estrés térmico húmedo severo "
                f"(<b>WBT máx = {wbt_max_rec:.1f} °C</b>), pero se detectan <b>{n_ageb_calor} unidades urbanas</b> con calentamiento superficial local "
                f"y déficit de dosel que requieren <b>{arb_restantes:,} árboles nativos</b>. Las áreas frescas o arboladas se muestran en verde (Conservación)."
            )

    st.subheader(f"Semáforo de Urgencia — {res['mun']}, {res['estado']}")
    st.markdown(f'<div class="banner-urgencia">{texto_urgencia}</div>', unsafe_allow_html=True)

    b1 = "Cobertura Arbórea: ESA WorldCover 10m" if micro_eval["wc_real"] else "Cobertura Arbórea: Sin dato real"
    if lst_normativo_ok:
        b2 = f"Calor Superficial: Landsat 8/9 ({n_escenas_lst} escenas)"
    elif n_escenas_lst > 0:
        b2 = f"Calor Superficial: Landsat 8/9 ({n_escenas_lst} escena{'s' if n_escenas_lst > 1 else ''} — respaldo <3)"
    else:
        b2 = "Calor Superficial: Sin dato real"
    b3 = "Clima 1950–2024: Reanálisis ERA5 (Open-Meteo)" if res["flags"]["era5_real"] else "Clima: Respaldo Demo"
    b4 = "Proyección: Emulación anclada a CMIP6 (WorldClim 2.1)" if res["cmip6_real"] else "Proyección: Escalamiento Demo"
    b5 = "Red Vial: OpenStreetMap" if micro_eval["calles_real"] else "Red Vial: No disponible"
    st.caption(f"Fuentes:  {b1}  |  {b2}  |  {b3}  |  {b4}  |  {b5}  |  Umbral aplicado: **>{res['umbral']} °C**")

    pdf_bytes = build_executive_pdf(
        municipio_nombre=f"{res['mun']}, {res['estado']}",
        resumen=micro_eval,
        tpa_val=tpa_reg if pd.notna(tpa_reg) else None,
        tse_val=tse_reg_pdf,
        iua_val=iua_pdf_str,
        umbral_c=res["umbral"],
        meta_copa=res["meta_copa"],
        tau_arb=tau_arb,
        anio_base=anio_base_cfg,
        wbt_max=float(ult_10_pdf["WBT_max_anual"].max()) if not ult_10_pdf.empty else None,
        dias_wbt28=float(ult_10_pdf["Dias_WBT28"].mean()) if not ult_10_pdf.empty else None,
        p99_lluvia=float(res["flags"]["p99_lluvia_mm"]),
        respaldo_activo=bool(respaldos) or en_demo,
        es_conservacion=es_conservacion,
    )

    st.download_button(
        label="Descargar Ficha Ejecutiva Municipal en PDF (One-Pager)" if not en_demo else "Descargar PDF de Demostración (Cifras Ilustrativas)",
        data=pdf_bytes,
        file_name=f"Ficha_Ejecutiva_{res['mun'].replace(' ', '_')}.pdf",
        mime="application/pdf",
        disabled=bloquear_pdf,
    )

    st.markdown("---")

    st.markdown("### Plan de Acción Prioritario")
    c_acc1, c_acc2, c_acc3 = st.columns(3)

    with c_acc1:
        if es_conservacion:
            st.markdown("""
                <div class="card-petroleo">
                    <b>Conservación de Dosel:</b> Mantener la cobertura vegetal existente y proteger corredores ribereños y forestales sin requerir plantación urbana masiva.
                </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
                <div class="card-petroleo">
                    <b>Infraestructura Verde:</b> Plantación de <b>{micro_eval['arboles_totales']:,} árboles nativos</b> en las AGEB urbanas que actualmente están por debajo de la meta del <b>{res['meta_copa']}%</b> de copa.
                </div>
            """, unsafe_allow_html=True)

    with c_acc2:
        if es_conservacion:
            st.markdown("""
                <div class="card-petroleo">
                    <b>Regulación Microclimática:</b> Preservar áreas permeables y vegetación ribereña que mantienen la estabilidad térmica del valle.
                </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
                <div class="card-petroleo">
                    <b>Mitigación Térmica (AbE):</b> Intervenir prioritariamente el <i>Quintil Superior</i> de déficit de sombra con arborización lineal en banquetas y camellones críticos.
                </div>
            """, unsafe_allow_html=True)

    with c_acc3:
        st.markdown("""
            <div class="card-petroleo">
                <b>Gestión Azul-Verde:</b> Implementar sistemas de infiltración pluvial y drenaje sostenible vinculados al Atlas de Riesgos municipal.
            </div>
        """, unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Copa total municipal*", f"{micro_eval['copa_media_pct']}%", help="Promedio sobre todo el polígono municipal (incluye áreas naturales/serranas).")
    c2.metric("TsE Regional (ERA5/CMIP6)", tse_reg_txt, help="Línea base primaria sin ajuste empírico de isla de calor (SSP5-8.5 P50).")
    c3.metric("TpA Regional disponible", tpa_reg_txt, help="Ventana de adaptación regional antes de TsE.")
    c4.metric(
        "Sensibilidad urbana (+ΔICU)",
        f"{int(round(tse_icu))}" if pd.notna(tse_icu) else ("No aplica" if es_conservacion else ">2100"),
        delta=None if es_conservacion else f"+{micro_eval['delta_icu_aire_c']} °C estimado",
        delta_color="off" if es_conservacion else "inverse",
        help="Escenario de sensibilidad aplicando ΔICU aire estimado desde LST (Voogt & Oke, 2003; Mildrexler et al., 2011).",
    )
    c5.metric("Déficit arbóreo (AGEB)", f"{micro_eval['arboles_totales']:,}", help="Suma exclusiva de unidades urbanas por debajo de la meta de copa.")

    renombre_ageb = {
        "Clave_AGEB": "Clave AGEB",
        "Colonia_Ref": "Colonia / Referencia",
        "Copa_pct": "Cobertura de Copa (%)",
        "LST_verano_C": "Temp. Superficial Verano (°C)",
        "IPS": "Índice Prioridad Arborización (0–100)",
        "Prioridad": "Nivel de Prioridad",
        "Arboles_equivalentes": "Árboles Requeridos",
    }

    if busqueda_colonia:
        mask_busq = gdf_ageb_eval["Clave_AGEB"].astype(str).str.contains(busqueda_colonia, case=False, na=False, regex=False)
        if "Colonia_Ref" in gdf_ageb_eval.columns:
            mask_busq = mask_busq | gdf_ageb_eval["Colonia_Ref"].astype(str).str.contains(busqueda_colonia, case=False, na=False, regex=False)
        filtradas = gdf_ageb_eval[mask_busq]
        if not filtradas.empty:
            st.success(f"Coincidencia encontrada: se localizaron {len(filtradas)} unidades urbanas.")
            cols_busq = [c for c in renombre_ageb.keys() if c in filtradas.columns]
            st.dataframe(filtradas[cols_busq].rename(columns=renombre_ageb), use_container_width=True, hide_index=True)
        else:
            st.warning("No se encontró ninguna colonia o AGEB con ese nombre en este municipio.")

    tab1, tab2, tab3, tab4 = st.tabs([
        "1. Mapa de Prioridad de Arborización",
        "2. Proyecciones Climáticas y Horizonte de Adaptación",
        "3. Estrés Térmico Húmedo y Precipitación Extrema",
        "4. Tablas y Descarga Excel",
    ])

    with tab1:
        st.markdown("**Zonas prioritarias de arborización y vialidades peatonales con exposición crítica a TsE**")
        if sin_conapo:
            st.info("Nota de comparabilidad: Capa socioeconómica CONAPO ausente para estas unidades; el Índice de Prioridad (IPS) se calculó exclusivamente con componentes biofísicos (copa y LST renormalizados al 100%) y no es comparable con municipios que integran marginación.")

        cent = res["poly"].centroid
        m = folium.Map(location=[cent.y, cent.x], zoom_start=12, tiles="OpenStreetMap", control_scale=True)

        def style_ageb(feat):
            prio = feat["properties"].get("Prioridad", "")
            if prio == "Quintil superior":
                return {"fillColor": "#d73027", "color": "#a50026", "weight": 1.2, "fillOpacity": 0.45}
            elif "Conservación" in prio:
                return {"fillColor": "#1a9850", "color": "#006837", "weight": 1.0, "fillOpacity": 0.35}
            return {"fillColor": "#fee08b", "color": "#bdbdbd", "weight": 0.6, "fillOpacity": 0.25}

        folium.GeoJson(
            gdf_ageb_eval[["Clave_AGEB", "Prioridad", "IPS", "Copa_pct", "LST_verano_C", "Arboles_equivalentes", "geometry"]],
            name="Prioridad de Arborización",
            style_function=style_ageb,
            tooltip=folium.GeoJsonTooltip(
                fields=["Clave_AGEB", "Prioridad", "IPS", "Copa_pct", "LST_verano_C", "Arboles_equivalentes"],
                aliases=["Unidad:", "Prioridad:", "Índice Prioridad (0–100):", "Copa (%):", "Temp. Sup. (°C):", "Árboles req.:"],
            ),
        ).add_to(m)

        df_ageb_deficit = gdf_ageb_eval[gdf_ageb_eval["Arboles_equivalentes"] > 0]
        if (not es_conservacion) and (not df_ageb_deficit.empty) and gdf_streets is not None and not gdf_streets.empty:
            zona_deficit = df_ageb_deficit.geometry.union_all()
            gdf_streets_activas = gpd.clip(gdf_streets, zona_deficit)
            gdf_streets_activas = gdf_streets_activas[~gdf_streets_activas.is_empty]
            if not gdf_streets_activas.empty:
                folium.GeoJson(
                    gdf_streets_activas,
                    name="Vialidades críticas (llegan primero a TsE)",
                    style_function=lambda _: {"color": "#67000d", "weight": 2.8, "opacity": 0.9},
                    tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["Calle prioritaria:"]),
                ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width=1100, height=520, returned_objects=[], key=f"map_{res['estado']}_{res['mun']}")
        st.caption("Escala gráfica en esquina inferior izquierda. Líneas en rojo oscuro: vialidades dentro de las unidades con mayor déficit de sombra y calor superficial.")

    with tab2:
        st.markdown(f"**Trayectoria histórica (1950–2024) y proyecciones emuladas ancladas a CMIP6 (Umbral > {res['umbral']} °C | Máximo referencia 1981–2010 = {res['limite']} días/año)**")
        fig_plume = plot_ipcc_plume(df_tx, res["limite"], tse_reg_plot, res["umbral"], f"{res['mun']}, {res['estado']}")
        st.pyplot(fig_plume, use_container_width=True)
        plt.close(fig_plume)

        if es_conservacion:
            st.info("Nota bioclimática: En municipios templados o tropicales de baja variabilidad interanual, el umbral estadístico de emergencia (TsE) puede superarse temprano sin implicar peligro térmico absoluto (LST < 30 °C y WBT < 26.5 °C).")

        st.markdown("**Resumen por escenario climático y horizonte temporal (Línea base regional + Sensibilidad urbana ΔICU)**")
        df_tpa_view = df_tpa.copy()
        for col_yr in ["TSE_regional", "TSE_con_ICU"]:
            if col_yr in df_tpa_view.columns:
                df_tpa_view[col_yr] = df_tpa_view[col_yr].apply(lambda v: f"{int(round(v))}" if pd.notna(v) else ">2100")
        for col_tp in ["TpA_anios", "TpA_con_ICU"]:
            if col_tp in df_tpa_view.columns:
                df_tpa_view[col_tp] = df_tpa_view[col_tp].apply(lambda v: f"{v:.1f}" if pd.notna(v) else f">{horizonte_max_cota}")

        renombre_tpa = {
            "Escenario": "Escenario CMIP6",
            "Percentil": "Percentil del Ensamble",
            "TSE_regional": "TsE Regional (Línea Base)",
            "TpA_anios": "TpA Regional (años)",
            "r_tendencia_C_anio": "Tasa Calentamiento (°C/año)",
            "Adelanto_ICU_anios": "Adelanto Sensibilidad ΔICU (años)",
            "TSE_con_ICU": "TsE Urbano (+ΔICU)",
            "TpA_con_ICU": "TpA Urbano (años)",
            "IUA_acotado": "IUA Urbano",
        }
        cols_tpa = [c for c in renombre_tpa.keys() if c in df_tpa_view.columns]
        st.dataframe(df_tpa_view[cols_tpa].rename(columns=renombre_tpa), use_container_width=True, hide_index=True)

    with tab3:
        st.markdown("**Índices extremos históricos (1950–2024): Temperatura de Bulbo Húmedo (WBT) y Precipitación Extrema (R99p)**")
        w1, w2, w3 = st.columns(3)
        ult_10 = df_hist[df_hist["Anio"] >= 2015]
        w1.metric("WBT máximo reciente (2015–2024)", f"{ult_10['WBT_max_anual'].max():.1f} °C")
        w2.metric("Días/año con WBT ≥ 28 °C (reciente)", f"{ult_10['Dias_WBT28'].mean():.1f} días")
        w3.metric("Umbral lluvia extrema local (P99)", f"{res['flags']['p99_lluvia_mm']} mm/24h")

        col_a, col_b = st.columns(2)
        with col_a:
            fig_wbt = plot_climate_index_bars(
                df_hist,
                col_name="Dias_WBT28",
                titulo="Estrés Térmico Húmedo (Días con WBT ≥ 28 °C)",
                ylabel="Días por año",
                color_bar="#0B3C49",
                color_trend="#9B2C2C",
            )
            st.pyplot(fig_wbt, use_container_width=True)
            plt.close(fig_wbt)

        with col_b:
            fig_rain = plot_climate_index_bars(
                df_hist,
                col_name="Dias_lluvia_ext",
                titulo=f"Precipitación Extrema R99p (Días > {res['flags']['p99_lluvia_mm']} mm/24h)",
                ylabel="Días por año",
                color_bar="#2B6CB0",
                color_trend="#0B3C49",
            )
            st.pyplot(fig_rain, use_container_width=True)
            plt.close(fig_rain)

        st.markdown(
            '<div class="banner-urgencia"><b>Criterio de infraestructura azul-verde:</b> En las unidades del Quintil Superior de déficit de sombra que además presentan recurrencia de precipitación extrema (R99p), '
            'se recomienda priorizar <b>jardines de lluvia, alcorques inundables y pavimentos permeables</b> sobre las vialidades críticas para mitigar simultáneamente '
            'la isla de calor y la escorrentía superficial.</div>',
            unsafe_allow_html=True,
        )

    with tab4:
        st.markdown("**Desglose por Unidad Geoestadística Básica (AGEB) — Primeras 30 unidades priorizadas**")
        cols_tabla = [c for c in renombre_ageb.keys() if c in gdf_ageb_eval.columns]
        st.dataframe(
            gdf_ageb_eval[cols_tabla].head(30).rename(columns=renombre_ageb),
            use_container_width=True,
            hide_index=True,
        )
        excel_bytes = build_excel_report(
            municipio_nombre=f"{res['mun']}, {res['estado']}",
            df_ageb=gdf_ageb_eval.drop(columns=["geometry"]),
            df_tx=df_tx,
            df_tpa=df_tpa,
            limite_dias=res["limite"],
            tau_vals=(tau_arb, tau_cor, tau_ban),
            cfg=cfg,
            umbral_c=res["umbral"],
            micro=micro_eval,
        )
        st.download_button(
            label="Descargar Libro Excel Completo (.xlsx)",
            data=excel_bytes,
            file_name=f"IUA_{res['mun'].replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    with st.expander("Nota Metodológica, Supuestos y Procedencia de Datos"):
        st.markdown("""
        * **Estándares científicos empleados:**
          * **Tiempo sin Precedentes (TsE / *Climate Departure*):** Primer año en que el promedio móvil de 20 años de días cálidos extremos supera de forma sostenida el máximo anual observado en el periodo de referencia 1981–2010 (Mora et al., 2013).
          * **Índices de extremos climáticos (OMM / ETCCDI):** Días cálidos sobre el percentil 95 local (`TX95p`), precipitación extrema sobre el percentil 99 (`R99p`) y Temperatura de Bulbo Húmedo estimada mediante la aproximación psicrométrica de **Stull (2011)**.
          * **Tendencias históricas:** Estimadas mediante pendiente no paramétrica de **Theil-Sen** (`días/década`) sobre el periodo **1950–2024** (Reanálisis ERA5 vía Open-Meteo).
        * **Constructos operativos y capas de emulación del marco IUA México:**
          * **Proyecciones climáticas:** Trayectorias anuales emuladas a partir de anomalías multimodelo CMIP6 (WorldClim 2.1: ACCESS-CM2, MPI-ESM1-2-HR, MRI-ESM2-0) ancladas a la tendencia local observada.
          * **Umbral operativo de estrés térmico húmedo (`WBT ≥ 28 °C`):** Umbral de severidad adoptado por el marco IUA para alerta de calor húmedo urbano (frente al límite fisiológico extremo de 35 °C documentado en Sherwood & Huber, 2010).
          * **Sensibilidad por Isla de Calor Urbana ($\Delta\text{ICU}$):** Parametrización empírica de cribado a partir del gradiente térmico superficial Landsat con compuesto mínimo de 3 escenas estivales (Voogt & Oke, 2003; Mildrexler et al., 2011), presentada como escenario urbano complementario a la línea base regional.
          * **Tiempo para Actuar ($TpA$) e Índice de Urgencia Adaptativa ($IUA = \tau / TpA$):** Razón entre el tiempo de consolidación vegetal ($\tau$) y la ventana disponible ($TpA$). Valores $\ge 1.0$ indican urgencia crítica; $0.70–0.99$ urgencia alta; $< 0.70$ ventana abierta.
        """)