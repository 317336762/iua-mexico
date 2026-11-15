import json
import os
import numpy as np
import pandas as pd
import requests

HEADERS = {"User-Agent": "IUA-Mexico-DecisionTool/1.0 (contact: academic-gis)"}
CACHE_DIR = "data/processed/cache_municipios"


def calc_wbt_from_tmax_tmin(tmax: np.ndarray, tmin: np.ndarray) -> np.ndarray:
    es_tmax = 0.6108 * np.exp((17.27 * tmax) / (tmax + 237.3))
    ea_tmin = 0.6108 * np.exp((17.27 * tmin) / (tmin + 237.3))
    rh_c = np.clip((ea_tmin / np.maximum(es_tmax, 0.1)) * 100.0, 10.0, 95.0)
    term1 = tmax * np.arctan(0.151977 * np.sqrt(rh_c + 8.313659))
    term2 = np.arctan(tmax + rh_c)
    term3 = np.arctan(rh_c - 1.676331)
    term4 = 0.00391838 * (rh_c ** 1.5) * np.arctan(0.023101 * rh_c)
    return term1 + term2 - term3 + term4 - 4.686035


def extract_historical_tx_series(era5_dir: str, polygon, umbral_tx: float = 35.0, usar_p95: bool = False) -> tuple[pd.DataFrame, dict]:
    lat = round(float(polygon.centroid.y), 4)
    lon = round(float(polygon.centroid.x), 4)
    os.makedirs(CACHE_DIR, exist_ok=True)
    raw_cache = os.path.join(CACHE_DIR, f"era5_{lat}_{lon}.json")

    flags = {"era5_real": False, "umbral_efectivo_C": umbral_tx, "p99_lluvia_mm": 50.0}
    daily = None

    if os.path.exists(raw_cache):
        with open(raw_cache, "r", encoding="utf-8") as f:
            daily = json.load(f)
    else:
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}&start_date=1950-01-01&end_date=2024-12-31"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=America%2FMexico_City"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            daily = r.json()["daily"]
            with open(raw_cache, "w", encoding="utf-8") as f:
                json.dump(daily, f)
        except Exception:
            daily = None

    if daily:
        df_d = pd.DataFrame({
            "date": pd.to_datetime(daily["time"]),
            "tmax": pd.to_numeric(daily["temperature_2m_max"], errors="coerce"),
            "tmin": pd.to_numeric(daily["temperature_2m_min"], errors="coerce"),
            "rain": pd.Series(pd.to_numeric(daily["precipitation_sum"], errors="coerce")).fillna(0.0),
        }).dropna(subset=["tmax"])
        df_d["tmin"] = df_d["tmin"].fillna(df_d["tmax"] - 12.0)

        df_d["Anio"] = df_d["date"].dt.year
        ref_d = df_d[(df_d["Anio"] >= 1981) & (df_d["Anio"] <= 2010)]

        if usar_p95 and not ref_d.empty:
            umbral_tx = round(float(np.percentile(ref_d["tmax"], 95)), 1)

        wet_days = ref_d[ref_d["rain"] > 1.0]["rain"]
        p99_rain = round(float(np.percentile(wet_days, 99)), 1) if len(wet_days) > 20 else 50.0
        umbral_lluvia = max(35.0, p99_rain)

        df_d["wbt"] = calc_wbt_from_tmax_tmin(df_d["tmax"].values, df_d["tmin"].values)
        df_d["excede_tx"] = (df_d["tmax"] > umbral_tx).astype(int)
        df_d["excede_wbt28"] = (df_d["wbt"] >= 28.0).astype(int)
        df_d["lluvia_extrema"] = (df_d["rain"] >= umbral_lluvia).astype(int)

        grp = df_d.groupby("Anio").agg(
            Ref_historica=("excede_tx", "sum"),
            Tmax_media=("tmax", "mean"),
            Dias_WBT28=("excede_wbt28", "sum"),
            WBT_max_anual=("wbt", "max"),
            Dias_lluvia_ext=("lluvia_extrema", "sum"),
            Lluvia_max_24h=("rain", "max"),
        ).reset_index()

        flags["era5_real"] = True
        flags["umbral_efectivo_C"] = umbral_tx
        flags["p99_lluvia_mm"] = round(umbral_lluvia, 1)
        return grp, flags

    base_days = max(15.0, (42.0 - umbral_tx) * 10.0)
    years = np.arange(1950, 2025)
    rng = np.random.default_rng(int(abs(lat * 1000)))
    trend = np.maximum(0, (years - 1985) * 0.25)
    days = np.round(np.clip(base_days + trend + rng.normal(0, 4.0, len(years)), 0, 220), 0)
    tmax_m = 30.5 + np.maximum(0, (years - 1985) * 0.035) + rng.normal(0, 0.35, len(years))
    grp = pd.DataFrame({
        "Anio": years,
        "Ref_historica": days,
        "Tmax_media": tmax_m,
        "Dias_WBT28": np.round(np.clip(4.0 + trend * 0.15, 0, 60), 0),
        "WBT_max_anual": np.round(25.0 + np.maximum(0, (years - 1985) * 0.02), 1),
        "Dias_lluvia_ext": rng.poisson(2.0, len(years)),
        "Lluvia_max_24h": np.round(rng.uniform(35, 85, len(years)), 1),
    })
    return grp, flags


def fetch_cmip6_local(polygon) -> dict | None:
    cmip_json = "data/raw/sig/cmip6_municipios.json"
    if not os.path.exists(cmip_json):
        return None
    try:
        import geopandas as gpd
        gdf = gpd.read_file("data/raw/sig/municipios_mexico.geojson")
        idx = gdf.geometry.distance(polygon.centroid).idxmin()
        key = f"{gdf.loc[idx, 'ESTADO']}_{gdf.loc[idx, 'MUNICIPIO']}"
        with open(cmip_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key)
    except Exception:
        return None


def generate_serie_tx_and_tpa(
    polygon,
    df_hist: pd.DataFrame,
    delta_icu_c: float,
    anio_base: int = 2026,
    umbral_tx: float = 35.0,
) -> tuple[pd.DataFrame, pd.DataFrame, float, bool]:
    ref_window = df_hist[(df_hist["Anio"] >= 1981) & (df_hist["Anio"] <= 2010)]
    limite_dias = float(ref_window["Ref_historica"].max()) if not ref_window.empty else 30.0
    if limite_dias < 5.0:
        limite_dias = 5.0

    # Tasa observada reciente (1975-2024) en °C/año como línea base física
    recent_win = df_hist[df_hist["Anio"] >= 1975]
    if len(recent_win) > 10:
        slope_hist, _ = np.polyfit(recent_win["Anio"], recent_win["Tmax_media"], 1)
    else:
        slope_hist = 0.028
    r_base = float(np.clip(slope_hist, 0.024, 0.042))

    years_all = np.arange(1950, 2101)
    df_tx = pd.DataFrame({"Año": years_all})
    df_tx = df_tx.merge(df_hist[["Anio", "Ref_historica"]], left_on="Año", right_on="Anio", how="left").drop(columns=["Anio"])

    cmip_vals = fetch_cmip6_local(polygon)
    cmip6_real = cmip_vals is not None and cmip_vals.get("ssp585_acc") is not None

    # Factores diferenciales por trayectoria socioeconómica y dispersión de ensamble
    scenarios = {
        "SSP2-4.5 P10": (0.42, 0.90),
        "SSP2-4.5 P50 (mediana)": (0.68, 1.15),
        "SSP2-4.5 P90": (0.98, 1.45),
        "SSP5-8.5 P10": (0.78, 1.30),
        "SSP5-8.5 P50 (mediana)": (1.15, 1.70),
        "SSP5-8.5 P90": (1.60, 2.15),
    }

    # Variabilidad interanual compartida para garantizar monotonicidad P10 <= P50 <= P90
    rng = np.random.default_rng(42)
    fut_mask = df_tx["Año"] >= 2015
    dt_yrs = (df_tx.loc[fut_mask, "Año"] - 2015).to_numpy(dtype=float)
    shared_noise = rng.normal(0, 3.5, len(dt_yrs))

    base_2015 = float(df_tx[df_tx["Año"].between(1995, 2020)]["Ref_historica"].mean())
    if np.isnan(base_2015):
        base_2015 = limite_dias * 0.60

    ref_tmax_mean = float(ref_window["Tmax_media"].mean()) if not ref_window.empty else 28.0

    # Fracción diurna de la isla de calor sobre Tmax (Oke et al., 2017: ~25% del pico nocturno/aire)
    delta_tmax_icu = 0.25 * float(delta_icu_c)

    tpa_rows = []
    prev_tse_by_scen = {}

    for col_name, (days_rate_base, mult_scen) in scenarios.items():
        scen_label, perc_label = col_name.split(" ", 1)
        r_scen = r_base * mult_scen
        days_rate = days_rate_base

        if cmip6_real:
            prefix = "ssp585" if "SSP5" in col_name else "ssp245"
            vals = [float(cmip_vals[f"{prefix}_{m}"]) for m in ["acc", "mpi", "mri"] if cmip_vals.get(f"{prefix}_{m}") is not None]
            if vals:
                q = 10 if "P10" in col_name else (90 if "P90" in col_name else 50)
                raw_val = float(np.percentile(vals, q))
                # Detecta si el JSON local guarda anomalías (<10 °C) o temperaturas absolutas (>=10 °C)
                delta_cmip = raw_val if raw_val < 10.0 else (raw_val - ref_tmax_mean)
                if delta_cmip > 0.8:
                    # Horizonte medio de proyección (~55 años respecto a 1995) modulando el percentil
                    q_scale = 0.85 if q == 10 else (1.18 if q == 90 else 1.0)
                    r_scen = (delta_cmip / 55.0) * q_scale
                    days_rate = days_rate_base * (r_scen / (r_base * mult_scen))

        r_scen = round(float(r_scen), 4)
        accel = 1.0 + (0.007 * dt_yrs if "SSP5" in col_name else 0.0015 * dt_yrs)
        sim_days = np.round(np.clip(base_2015 + days_rate * dt_yrs * accel + shared_noise, 0, 365), 1)
        df_tx.loc[fut_mask, col_name] = sim_days

        roll_20 = df_tx[col_name].rolling(20, min_periods=20).mean()
        central_years = df_tx["Año"] - 9

        exceed = central_years[(roll_20 > limite_dias) & (central_years >= 2024)]
        if not exceed.empty:
            tse_reg = int(exceed.min())
        else:
            tse_reg = 2085 if "SSP2" in col_name else 2065

        # Garantiza orden físico dentro de cada escenario: TsE(P10) >= TsE(P50) >= TsE(P90)
        if scen_label in prev_tse_by_scen and tse_reg > prev_tse_by_scen[scen_label]:
            tse_reg = prev_tse_by_scen[scen_label]
        prev_tse_by_scen[scen_label] = tse_reg

        # Adelanto consistente con la fórmula metodológica: ΔTmax_ICU / r_scen
        adelanto_icu = round(delta_tmax_icu / max(r_scen, 0.015), 1)
        tse_icu = round(tse_reg - adelanto_icu, 1)

        tpa_reg = round(float(tse_reg - anio_base), 1)
        tpa_icu = round(float(tse_icu - anio_base), 1)

        tpa_rows.append({
            "Escenario": scen_label,
            "Percentil": perc_label,
            "TSE_regional": tse_reg,
            "TpA_anios": tpa_reg,
            "r_tendencia_C_anio": r_scen,
            "Adelanto_ICU_anios": adelanto_icu,
            "TSE_con_ICU": tse_icu,
            "TpA_con_ICU": tpa_icu,
        })

    return df_tx, pd.DataFrame(tpa_rows), limite_dias, cmip6_real