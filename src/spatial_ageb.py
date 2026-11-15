import json
import os
import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import requests
from rasterio.mask import mask
from rasterstats import zonal_stats
from shapely.geometry import LineString, box

CACHE_DIR = "data/processed/cache_municipios"


def get_utm_epsg(lon: float) -> str:
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def build_urban_grid_or_ageb(polygon) -> gpd.GeoDataFrame:
    ageb_local = "data/raw/sig/ageb.shp"
    utm = get_utm_epsg(polygon.centroid.x)

    if os.path.exists(ageb_local):
        gdf = gpd.read_file(ageb_local).to_crs("EPSG:4326")
        gdf = gdf[gdf.intersects(polygon)].copy()
        if not gdf.empty:
            cve_col = next((c for c in ["CVEGEO", "CVE_AGEB", "cvegeo"] if c in gdf.columns), None)
            gdf["Clave_AGEB"] = gdf[cve_col] if cve_col else [f"AGEB_{i+1:04d}" for i in range(len(gdf))]
            gdf["Colonia_Ref"] = gdf["NOM_LOC"] if "NOM_LOC" in gdf.columns else "AGEB Urbana"
            gdf["Area_ha"] = gdf.to_crs(utm).geometry.area / 10000.0
            return gdf[["Clave_AGEB", "Colonia_Ref", "Area_ha", "geometry"]]

    poly_utm = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(utm).iloc[0]
    minx, miny, maxx, maxy = poly_utm.bounds
    step = 700.0
    cells, idx = [], 1
    for x in np.arange(minx, maxx, step):
        for y in np.arange(miny, maxy, step):
            cell = box(x, y, x + step, y + step).intersection(poly_utm)
            if not cell.is_empty and cell.area > 50000:
                cells.append({
                    "Clave_AGEB": f"U-{idx:04d}",
                    "Colonia_Ref": "Unidad Urbana",
                    "Area_ha": cell.area / 10000.0,
                    "geometry": cell,
                })
                idx += 1

    return gpd.GeoDataFrame(cells, crs=utm).to_crs("EPSG:4326")


def clip_to_poly(src, polygon):
    poly_proj = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(src.crs).iloc[0]
    return mask(src, [poly_proj], crop=True)


def fetch_fast_streets(top_geom) -> gpd.GeoDataFrame | None:
    # 1. Intento principal con OSMnx usando el área real + buffer de 300m
    try:
        import osmnx as ox
        ox.settings.use_cache = True
        ox.settings.timeout = 30
        
        # Buffer de ~300m en grados para asegurar cobertura de las unidades críticas
        search_area = top_geom.buffer(0.003)
        G = ox.graph_from_polygon(search_area, network_type="all", simplify=True)
        edges = ox.graph_to_gdfs(G, nodes=False).reset_index()
        edges = edges[edges.intersects(top_geom.buffer(0.0005))].copy()
        
        if not edges.empty:
            if "name" in edges.columns:
                edges["name"] = edges["name"].apply(
                    lambda x: ", ".join(x) if isinstance(x, list) else (str(x) if pd.notna(x) else "Vialidad prioritaria")
                )
            else:
                edges["name"] = "Vialidad prioritaria"
            return edges[["name", "geometry"]].to_crs("EPSG:4326")
    except Exception:
        pass

    # 2. Respaldo directo vía Overpass API (sin depender de grafos pesados de OSMnx)
    try:
        minx, miny, maxx, maxy = top_geom.buffer(0.002).bounds
        query = f"""
        [out:json][timeout:25];
        way["highway"~"primary|secondary|tertiary|residential"]({miny},{minx},{maxy},{maxx});
        out geom;
        """
        resp = requests.post("https://overpass-api.de/api/interpreter", data={"data": query}, timeout=25)
        if resp.status_code == 200:
            elements = resp.json().get("elements", [])
            rows = []
            for el in elements:
                coords = [(pt["lon"], pt["lat"]) for pt in el.get("geometry", [])]
                if len(coords) >= 2:
                    name = el.get("tags", {}).get("name", "Vialidad prioritaria")
                    rows.append({"name": name, "geometry": LineString(coords)})
            if rows:
                gdf_ov = gpd.GeoDataFrame(rows, crs="EPSG:4326")
                gdf_ov = gdf_ov[gdf_ov.intersects(top_geom.buffer(0.0005))].copy()
                if not gdf_ov.empty:
                    return gdf_ov[["name", "geometry"]]
    except Exception:
        pass

    return None

def compute_marginacion(gdf_base: gpd.GeoDataFrame, copa_pcts: list, lst_vals: list) -> np.ndarray:
    fallback = np.round(np.clip(100 - np.array(copa_pcts) * 2.2 + (np.array(lst_vals) - np.mean(lst_vals)) * 4, 5, 95), 2)
    conapo_csv = "data/raw/sig/marginacion_conapo.csv"
    if not os.path.exists(conapo_csv):
        return fallback
    try:
        df_con = pd.read_csv(conapo_csv, dtype={"CVEGEO": str})
        val_col = next((c for c in ["IMN_2020", "IM_2020", "IMN", "IM"] if c in df_con.columns), None)
        if not val_col or "CVEGEO" not in df_con.columns:
            return fallback
        m_map = dict(zip(df_con["CVEGEO"].str.strip(), pd.to_numeric(df_con[val_col], errors="coerce")))
        raw_m = gdf_base["Clave_AGEB"].astype(str).map(m_map)
        if not raw_m.notna().any():
            return fallback
        m_norm = 100.0 * (1.0 - raw_m) if "IMN" in val_col else (raw_m - raw_m.min()) / max(raw_m.max() - raw_m.min(), 1e-6) * 100.0
        return np.round(m_norm.fillna(50.0).values, 2)
    except Exception:
        return fallback


def compute_prioridad_sombra(
    polygon,
    mun_id: str,
    cfg: dict,
    meta_copa: float = 25.0,
    pesos: tuple[float, float, float] = (0.45, 0.35, 0.20),
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None, dict]:
    mun_dir = os.path.join(CACHE_DIR, mun_id)
    os.makedirs(mun_dir, exist_ok=True)
    base_geojson = os.path.join(mun_dir, "unidades_base.geojson")
    meta_json = os.path.join(mun_dir, "micro_summary.json")
    streets_geojson = os.path.join(mun_dir, "calles_criticas.geojson")

    if os.path.exists(base_geojson) and os.path.exists(meta_json):
        gdf_base = gpd.read_file(base_geojson)
        with open(meta_json, "r", encoding="utf-8") as f:
            summary = json.load(f)
    else:
        gdf_units = build_urban_grid_or_ageb(polygon)
        bbox = list(polygon.bounds)
        wc_real, lst_real = False, False

        catalog = pystac_client.Client.open(
            "https://planetarycomputer.microsoft.com/api/stac/v1",
            modifier=planetary_computer.sign_inplace,
        )

        wc_tif = os.path.join(mun_dir, "worldcover.tif")
        if not os.path.exists(wc_tif):
            try:
                items_wc = list(catalog.search(collections=["esa-worldcover"], bbox=bbox, max_items=1).items())
                if items_wc:
                    with rasterio.open(items_wc[0].assets["map"].href) as src:
                        out_img, out_trans = clip_to_poly(src, polygon)
                        meta = src.meta.copy()
                        meta.update({"height": out_img.shape[1], "width": out_img.shape[2], "transform": out_trans})
                        with rasterio.open(wc_tif, "w", **meta) as dst:
                            dst.write(out_img)
            except Exception:
                pass

        copa_pcts = []
        if os.path.exists(wc_tif):
            wc_real = True
            gdf_wc = gdf_units.to_crs(rasterio.open(wc_tif).crs)
            for st in zonal_stats(gdf_wc, wc_tif, categorical=True):
                total_px = sum(v for k, v in st.items() if k != 0)
                copa_pcts.append(round((st.get(10, 0) / total_px * 100.0) if total_px > 0 else 5.0, 2))
        else:
            copa_pcts = [8.0] * len(gdf_units)

        lst_tif = os.path.join(mun_dir, "lst_verano.tif")
        if not os.path.exists(lst_tif):
            try:
                items_ls = list(catalog.search(
                    collections=["landsat-c2-l2"],
                    intersects=polygon.__geo_interface__,
                    datetime="2023-06-01/2025-09-30",
                    query={"eo:cloud_cover": {"lt": 15}},
                    max_items=2,
                ).items())
                if items_ls and "lwir11" in items_ls[0].assets:
                    with rasterio.open(items_ls[0].assets["lwir11"].href) as src:
                        out_lst, out_trans = clip_to_poly(src, polygon)
                        lst_c = np.where(out_lst > 0, (out_lst * 0.00341802 + 149.0) - 273.15, np.nan).astype(np.float32)
                        meta = src.meta.copy()
                        meta.update({"dtype": "float32", "nodata": np.nan, "height": lst_c.shape[1], "width": lst_c.shape[2], "transform": out_trans})
                        with rasterio.open(lst_tif, "w", **meta) as dst:
                            dst.write(lst_c)
            except Exception:
                pass

        if os.path.exists(lst_tif):
            lst_real = True
            gdf_lst = gdf_units.to_crs(rasterio.open(lst_tif).crs)
            lst_vals = [round(float(s["mean"]), 2) if s["mean"] is not None else 38.0 for s in zonal_stats(gdf_lst, lst_tif, stats=["mean"])]
        else:
            lst_vals = [38.0] * len(gdf_units)

        gdf_base = gdf_units.copy()
        gdf_base["Copa_pct"] = copa_pcts
        gdf_base["LST_verano_C"] = lst_vals
        gdf_base["Marginacion_idx"] = compute_marginacion(gdf_base, copa_pcts, lst_vals)
        gdf_base.to_file(base_geojson, driver="GeoJSON")

        delta_icu_aire = round(float(np.clip((np.percentile(lst_vals, 90) - np.percentile(lst_vals, 25)) * 0.45, 1.2, 2.2)), 2)
        summary = {
            "delta_icu_aire_c": delta_icu_aire,
            "altura_edificios_m": 6.5,
            "wc_real": wc_real,
            "lst_real": lst_real,
        }
        with open(meta_json, "w", encoding="utf-8") as f:
            json.dump(summary, f)

    df = gdf_base.copy()
    wC, wT, wS = pesos
    copa_arbol = cfg["prioridad_sombra"]["copa_arbol_adulto_m2"]

    df["FC"] = 100.0 * (meta_copa - np.minimum(df["Copa_pct"], meta_copa)) / max(meta_copa, 1.0)
    t_min, t_max = df["LST_verano_C"].min(), df["LST_verano_C"].max()
    df["FT"] = 0.0 if t_max == t_min else 100.0 * (df["LST_verano_C"] - t_min) / (t_max - t_min)
    m_min, m_max = df["Marginacion_idx"].min(), df["Marginacion_idx"].max()
    df["FS"] = 0.0 if m_max == m_min else 100.0 * (df["Marginacion_idx"] - m_min) / (m_max - m_min)

    df["IPS"] = np.round(wC * df["FC"] + wT * df["FT"] + wS * df["FS"], 2)
    df["Lugar"] = df["IPS"].rank(ascending=False, method="min").astype(int)
    p80 = np.percentile(df["IPS"], 80)
    df["Prioridad"] = np.where(
        df["Copa_pct"] >= meta_copa,
        "Conservación (cumple la meta)",
        np.where(df["IPS"] >= p80, "Quintil superior", "Resto"),
    )
    df["Brecha_copa_ha"] = np.round(np.maximum(0.0, (meta_copa - df["Copa_pct"]) / 100.0 * df["Area_ha"]), 3)
    df["Arboles_equivalentes"] = np.round(df["Brecha_copa_ha"] * 10000.0 / copa_arbol, 0).astype(int)
    df = df.sort_values("Lugar").reset_index(drop=True)

    summary["copa_media_pct"] = round(float(df["Copa_pct"].mean()), 2)
    summary["lst_media_c"] = round(float(df["LST_verano_C"].mean()), 2)
    summary["brecha_total_ha"] = round(float(df["Brecha_copa_ha"].sum()), 2)
    summary["arboles_totales"] = int(df["Arboles_equivalentes"].sum())

    gdf_streets = None
    if os.path.exists(streets_geojson):
        try:
            gdf_streets = gpd.read_file(streets_geojson)
        except Exception:
            gdf_streets = None
    else:
        gdf_streets = fetch_fast_streets(df.head(3).geometry.union_all())
        if gdf_streets is not None and not gdf_streets.empty:
            gdf_streets.to_file(streets_geojson, driver="GeoJSON")

    summary["calles_real"] = gdf_streets is not None and not gdf_streets.empty
    return df, gdf_streets, summary