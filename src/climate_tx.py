import json
import os
import numpy as np
import pandas as pd
import requests

HEADERS = {"User-Agent": "IUA-Mexico-DecisionTool/2.0 (contact: martinezbaruc13@gmail.com)"}
CACHE_DIR = "data/processed/cache_municipios"


def calc_wbt_from_tmax_tmin(tmax: np.ndarray, tmin: np.ndarray) -> np.ndarray:
    """Temperatura de bulbo húmedo (Stull, 2011) con RH estimada a partir de Tmin/Tmax."""
    es_tmax = 0.6108 * np.exp((17.27 * tmax) / (tmax + 237.3))
    ea_tmin = 0.6108 * np.exp((17.27 * tmin) / (tmin + 237.3))
    rh_c = np.clip((ea_tmin / np.maximum(es_tmax, 0.1)) * 100.0, 10.0, 95.0)
    term1 = tmax * np.arctan(0.151977 * np.sqrt(rh_c + 8.313659))
    term2 = np.arctan(tmax + rh_c)
    term3 = np.arctan(rh_c - 1.676331)
    term4 = 0.00391838 * (rh_c ** 1.5) * np.arctan(0.023101 * rh_c)
    return term1 + term2 - term3 + term4 - 4.686035


def extract_historical_tx_series(
    era5_dir: str,
    polygon,
    umbral_tx: float = 35.0,
    usar_p95: bool = False,
    strict_mode: bool = True,
) -> tuple[pd.DataFrame, dict]:
    lat = round(float(polygon.centroid.y), 4)
    lon = round(float(polygon.centroid.x), 4)
    os.makedirs(CACHE_DIR, exist_ok=True)
    raw_cache = os.path.join(CACHE_DIR, f"era5_{lat}_{lon}.json")

    flags = {
        "era5_real": False,
        "fuente_clima": "Reanálisis ERA5 vía Open-Meteo (1950–2024)",
        "umbral_efectivo_C": umbral_tx,
        "p99_lluvia_mm": 50.0,
    }
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
        except Exception as exc:
            if strict_mode:
                raise RuntimeError(
                    f"Fallo al obtener serie histórica ERA5 (Open-Meteo) para ({lat}, {lon}) "
                    f"y no existe caché local. Active el Modo Demostración para vistas ilustrativas. Detalle: {exc}"
                ) from exc
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

    # Solo accesible explícitamente cuando strict_mode=False (Modo Demostración)
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
    flags["fuente_clima"] = "SERIE SINTÉTICA DE DEMOSTRACIÓN (no válida para uso normativo)"
    return grp, flags


def fetch_cmip6_local(polygon) -> tuple[dict | None, dict]:
    """Carga proyecciones CMIP6 municipales preprocesadas con metadatos explícitos de unidades."""
    cmip_json = "data/raw/sig/cmip6_municipios.json"
    meta_default = {
        "unidad": "temperatura_absoluta_C",  # WorldClim 2.1 CMIP6 bio/tmax (2041-2060)
        "horizonte_anios": 55.0,             # Punto medio 2050 vs línea base 1981-2010 (1995)
        "modelos": ["ACCESS-CM2", "MPI-ESM1-2-HR", "MRI-ESM2-0"],
    }
    if not os.path.exists(cmip_json):
        return None, meta_default
    try:
        import geopandas as gpd
        gdf = gpd.read_file("data/raw/sig/municipios_mexico.geojson")
        idx = gdf.geometry.distance(polygon.centroid).idxmin()
        key = f"{gdf.loc[idx, 'ESTADO']}_{gdf.loc[idx, 'MUNICIPIO']}"
        with open(cmip_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        meta = data.get("_meta", meta_default)
        return data.get(key), meta
    except Exception:
        return None, meta_default


def generate_serie_tx_and_tpa(
    polygon,
    df_hist: pd.DataFrame,
    delta_icu_c: float,
    anio_base: int = 2026,
    umbral_tx: float = 35.0,
    tau_consolidacion: float = 12.0,
    strict_mode: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, float, bool]:
    ref_window = df_hist[(df_hist["Anio"] >= 1981) & (df_hist["Anio"] <= 2010)]
    limite_dias = float(ref_window["Ref_historica"].max()) if not ref_window.empty else 30.0
    if limite_dias < 5.0:
        limite_dias = 5.0

    recent_win = df_hist[df_hist["Anio"] >= 1975]
    if len(recent_win) > 10:
        slope_hist, _ = np.polyfit(recent_win["Anio"], recent_win["Tmax_media"], 1)
    else:
        slope_hist = 0.028
    r_base = float(np.clip(slope_hist, 0.024, 0.042))

    years_all = np.arange(1950, 2101)
    df_tx = pd.DataFrame({"Año": years_all})
    df_tx = df_tx.merge(
        df_hist[["Anio", "Ref_historica"]], left_on="Año", right_on="Anio", how="left"
    ).drop(columns=["Anio"])

    cmip_vals, cmip_meta = fetch_cmip6_local(polygon)
    cmip6_real = cmip_vals is not None and any(
        cmip_vals.get(f"ssp585_{m}") is not None for m in ["acc", "mpi", "mri"]
    )

    if not cmip6_real and strict_mode:
        raise RuntimeError(
            "Proyecciones CMIP6 municipales no disponibles para este municipio en data/raw/sig/cmip6_municipios.json. "
            "Se bloquea el escalamiento heurístico en modo estricto. Active Modo Demostración para vistas ilustrativas."
        )

    # Parámetros de emulación de días cálidos:
    # Cuando cmip6_real=True, las tasas se anclan al delta térmico real del ensamble CMIP6.
    # Los factores siguientes solo operan en Modo Demostración (strict_mode=False).
    scenarios = {
        "SSP2-4.5 P10": (0.42, 0.90),
        "SSP2-4.5 P50 (mediana)": (0.68, 1.15),
        "SSP2-4.5 P90": (0.98, 1.45),
        "SSP5-8.5 P10": (0.78, 1.30),
        "SSP5-8.5 P50 (mediana)": (1.15, 1.70),
        "SSP5-8.5 P90": (1.60, 2.15),
    }

    rng = np.random.default_rng(42)
    fut_mask = df_tx["Año"] >= 2015
    dt_yrs = (df_tx.loc[fut_mask, "Año"] - 2015).to_numpy(dtype=float)
    shared_noise = rng.normal(0, 3.5, len(dt_yrs))

    base_2015 = float(df_tx[df_tx["Año"].between(1995, 2020)]["Ref_historica"].mean())
    if np.isnan(base_2015):
        base_2015 = limite_dias * 0.60

    ref_tmax_mean = float(ref_window["Tmax_media"].mean()) if not ref_window.empty else 28.0
    delta_tmax_icu = 0.25 * float(delta_icu_c)

    # Cota dinámica para casos donde el rebase ocurre posterior a 2100
    horizonte_max = max(2100 - anio_base, 1)
    iua_cota_2100 = round(float(tau_consolidacion) / float(horizonte_max), 3)

    unidad_cmip = cmip_meta.get("unidad", "temperatura_absoluta_C")
    horizonte_cmip = float(cmip_meta.get("horizonte_anios", 55.0))

    tpa_rows = []
    prev_tse_by_scen = {}

    for col_name, (days_rate_base, mult_scen) in scenarios.items():
        scen_label, perc_label = col_name.split(" ", 1)
        r_scen = r_base * mult_scen
        days_rate = days_rate_base
        metodo_fuente = (
            "Proyección emulada a partir de anomalías CMIP6 (WorldClim 2.1) + tendencia observada ERA5"
            if cmip6_real
            else "DEMONSTRACIÓN: Escalamiento heurístico de tendencia (no es salida de ensamble CMIP6)"
        )

        if cmip6_real:
            prefix = "ssp585" if "SSP5" in col_name else "ssp245"
            vals = [
                float(cmip_vals[f"{prefix}_{m}"])
                for m in ["acc", "mpi", "mri"]
                if cmip_vals.get(f"{prefix}_{m}") is not None
            ]
            if vals:
                q = 10 if "P10" in col_name else (90 if "P90" in col_name else 50)
                raw_val = float(np.percentile(vals, q))

                # Conversión explícita por metadato de unidad (sin umbral heurístico < 10.0)
                if unidad_cmip == "anomalia_C":
                    delta_cmip = raw_val
                else:
                    delta_cmip = raw_val - ref_tmax_mean

                delta_cmip = max(delta_cmip, 0.3)
                q_scale = 0.85 if q == 10 else (1.18 if q == 90 else 1.0)
                r_scen = (delta_cmip / horizonte_cmip) * q_scale
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
            # Garantiza monotonicidad física: TsE(P10) >= TsE(P50) >= TsE(P90)
            if scen_label in prev_tse_by_scen and prev_tse_by_scen[scen_label] is not None:
                if tse_reg > prev_tse_by_scen[scen_label]:
                    tse_reg = prev_tse_by_scen[scen_label]
            prev_tse_by_scen[scen_label] = tse_reg

            adelanto_icu = round(delta_tmax_icu / max(r_scen, 0.015), 1)
            tse_icu = round(tse_reg - adelanto_icu, 1)
            tpa_reg = round(float(tse_reg - anio_base), 1)
            tpa_icu = round(float(tse_icu - anio_base), 1)
            estado_horizonte = "Dentro de horizonte 2100"
            iua_ref = round(float(tau_consolidacion) / max(tpa_icu, 0.5), 3) if tpa_icu > 0 else np.nan
            iua_etiqueta = f"{iua_ref:.2f}" if tpa_icu > 0 else "Rebasado"
        else:
            # Sin imposición arbitraria de 2085/2065: se reporta explícitamente >2100
            tse_reg = np.nan
            adelanto_icu = round(delta_tmax_icu / max(r_scen, 0.015), 1)
            tse_icu = np.nan
            tpa_reg = np.nan
            tpa_icu = np.nan
            estado_horizonte = ">2100 (sin rebase en siglo XXI)"
            iua_etiqueta = f"< {iua_cota_2100:.2f} (>2100)"

        tpa_rows.append({
            "Escenario": scen_label,
            "Percentil": perc_label,
            "TSE_regional": tse_reg,
            "TpA_anios": tpa_reg,
            "r_tendencia_C_anio": r_scen,
            "Adelanto_ICU_anios": adelanto_icu,
            "TSE_con_ICU": tse_icu,
            "TpA_con_ICU": tpa_icu,
            "Horizonte": estado_horizonte,
            "IUA_acotado": iua_etiqueta,
            "Metodo_proyeccion": metodo_fuente,
        })

    return df_tx, pd.DataFrame(tpa_rows), limite_dias, cmip6_real