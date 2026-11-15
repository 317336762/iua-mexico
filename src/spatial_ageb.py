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
from rasterio.warp import Resampling, reproject
from rasterstats import zonal_stats
from shapely.geometry import LineString, box

CACHE_DIR = "data/processed/cache_municipios"


def get_utm_epsg(lon: float) -> str:
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def build_urban_grid_or_ageb(polygon) -> gpd.GeoDataFrame:
    utm = get_utm_epsg(polygon.centroid.x)
    ageb_candidates = [
        "data/raw/sig/ageb.parquet",
        "data/raw/sig/ageb.gpkg",
        "data/raw/sig/ageb.geojson.gz",
        "data/raw/sig/ageb.shp",
    ]
    ageb_local = next((p for p in ageb_candidates if os.path.exists(p)), None)

    if ageb_local is not None:
        gdf = (
            gpd.read_parquet(ageb_local)
            if ageb_local.endswith(".parquet")
            else gpd.read_file(ageb_local)
        )
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        else:
            gdf = gdf.to_crs("EPSG:4326")

        gdf = gdf[gdf.intersects(polygon)].copy()
        if not gdf.empty:
            cve_col = next((c for c in ["CVEGEO", "CVE_AGEB", "cvegeo"] if c in gdf.columns), None)
            nom_col = next((c for c in ["NOM_LOC", "COLONIA", "NOM_MUN", "nom_loc"] if c in gdf.columns), None)
            gdf["Clave_AGEB"] = gdf[cve_col].astype(str).str.strip() if cve_col else [f"AGEB_{i+1:04d}" for i in range(len(gdf))]
            gdf["Colonia_Ref"] = gdf[nom_col].fillna("AGEB Urbana").astype(str) if nom_col else "AGEB Urbana"
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


def mask_landsat_c2_qa_pixel(qa_arr: np.ndarray) -> np.ndarray:
    cloud_bits = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
    return (qa_arr & cloud_bits) == 0


def build_landsat_lst_composite(catalog, polygon, lst_tif: str, max_scenes: int = 5) -> int:
    try:
        search = catalog.search(
            collections=["landsat-c2-l2"],
            intersects=polygon.__geo_interface__,
            datetime="2022-05-01/2026-09-30",
            query={
                "eo:cloud_cover": {"lt": 20},
                "platform": {"in": ["landsat-8", "landsat-9"]},
            },
            max_items=12,
        )
        items = list(search.items())
    except Exception:
        return 0

    warm_items = [
        it for it in items
        if it.datetime is not None and it.datetime.month in (5, 6, 7, 8, 9)
        and "lwir11" in it.assets
    ]
    warm_items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100.0))
    selected = warm_items[:max_scenes]

    if not selected:
        return 0

    stack = []
    ref_meta = None
    ref_transform = None
    ref_crs = None
    ref_shape = None

    for item in selected:
        try:
            with rasterio.open(item.assets["lwir11"].href) as src_lwir:
                out_lst, out_trans = clip_to_poly(src_lwir, polygon)
                band_dn = out_lst[0].astype(np.float32)
                valid_mask = band_dn > 0

                qa_asset = item.assets.get("qa_pixel") or item.assets.get("QA_PIXEL")
                if qa_asset is not None:
                    with rasterio.open(qa_asset.href) as src_qa:
                        out_qa, _ = clip_to_poly(src_qa, polygon)
                        if out_qa[0].shape == band_dn.shape:
                            valid_mask &= mask_landsat_c2_qa_pixel(out_qa[0])

                lst_c = np.where(
                    valid_mask,
                    (band_dn * 0.00341802 + 149.0) - 273.15,
                    np.nan,
                ).astype(np.float32)

                lst_c = np.where((lst_c >= 5.0) & (lst_c <= 68.0), lst_c, np.nan)

                if np.isnan(lst_c).all():
                    continue

                if ref_meta is None:
                    ref_crs = src_lwir.crs
                    ref_transform = out_trans
                    ref_shape = lst_c.shape
                    ref_meta = src_lwir.meta.copy()
                    ref_meta.update({
                        "dtype": "float32",
                        "nodata": np.nan,
                        "height": ref_shape[0],
                        "width": ref_shape[1],
                        "transform": ref_transform,
                    })
                    stack.append(lst_c)
                else:
                    aligned_lst = np.full(ref_shape, np.nan, dtype=np.float32)
                    reproject(
                        source=lst_c,
                        destination=aligned_lst,
                        src_transform=out_trans,
                        src_crs=src_lwir.crs,
                        dst_transform=ref_transform,
                        dst_crs=ref_crs,
                        src_nodata=np.nan,
                        dst_nodata=np.nan,
                        resampling=Resampling.bilinear,
                    )
                    if not np.isnan(aligned_lst).all():
                        stack.append(aligned_lst)
        except Exception:
            continue

    if not stack or ref_meta is None:
        return 0

    arr_stack = np.stack(stack, axis=0)
    median_lst = np.nanmedian(arr_stack, axis=0).astype(np.float32)

    with rasterio.open(lst_tif, "w", **ref_meta) as dst:
        dst.write(median_lst, 1)

    return len(stack)


def fetch_fast_streets(top_geom) -> gpd.GeoDataFrame | None:
    if top_geom is None or top_geom.is_empty:
        return None

    minx, miny, maxx, maxy = top_geom.buffer(0.0025).bounds
    query = f"""
    [out:json][timeout:25];
    way["highway"~"primary|secondary|tertiary|residential|unclassified"]({miny},{minx},{maxy},{maxx});
    out geom;
    """
    overpass_mirrors = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    headers = {"User-Agent": "IUA-Mexico-UNAM/1.0 (academic-urban-climate)"}

    for endpoint in overpass_mirrors:
        try:
            resp = requests.post(endpoint, data={"data": query}, headers=headers, timeout=22)
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
                    gdf_ov = gdf_ov[gdf_ov.intersects(top_geom.buffer(0.0008))].copy()
                    if not gdf_ov.empty:
                        return gdf_ov[["name", "geometry"]]
        except Exception:
            continue

    try:
        import osmnx as ox
        ox.settings.use_cache = True
        ox.settings.timeout = 25
        search_area = top_geom.buffer(0.003).convex_hull
        G = ox.graph_from_polygon(search_area, network_type="all", simplify=True)
        edges = ox.graph_to_gdfs(G, nodes=False).reset_index()
        edges = edges[edges.intersects(top_geom.buffer(0.0008))].copy()
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

    return None


def compute_marginacion(gdf_base: gpd.GeoDataFrame) -> np.ndarray:
    nan_arr = np.full(len(gdf_base), np.nan, dtype=float)
    conapo_candidates = [
        "data/raw/sig/marginacion_conapo.parquet",
        "data/raw/sig/marginacion_conapo.csv.gz",
        "data/raw/sig/marginacion_conapo.csv",
    ]
    conapo_file = next((p for p in conapo_candidates if os.path.exists(p)), None)
    if conapo_file is None:
        return nan_arr
    try:
        df_con = (
            pd.read_parquet(conapo_file)
            if conapo_file.endswith(".parquet")
            else pd.read_csv(conapo_file, dtype={"CVEGEO": str})
        )
        val_col = next((c for c in ["IMN_2020", "IM_2020", "IMN", "IM"] if c in df_con.columns), None)
        cve_col = next((c for c in ["CVEGEO", "cvegeo", "CVE_AGEB"] if c in df_con.columns), None)
        if not val_col or not cve_col:
            return nan_arr
        m_map = dict(zip(df_con[cve_col].astype(str).str.strip(), pd.to_numeric(df_con[val_col], errors="coerce")))
        raw_m = gdf_base["Clave_AGEB"].astype(str).str.strip().map(m_map)
        if not raw_m.notna().any():
            return nan_arr
        m_norm = (
            100.0 * (1.0 - raw_m)
            if "IMN" in val_col
            else (raw_m - raw_m.min()) / max(raw_m.max() - raw_m.min(), 1e-6) * 100.0
        )
        return np.round(m_norm.values, 2)
    except Exception:
        return nan_arr


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
        n_escenas_lst = 0

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
            copa_pcts = [np.nan] * len(gdf_units)

        lst_tif = os.path.join(mun_dir, "lst_verano.tif")
        if not os.path.exists(lst_tif):
            n_escenas_lst = build_landsat_lst_composite(catalog, polygon, lst_tif, max_scenes=5)
        else:
            n_escenas_lst = 1

        if os.path.exists(lst_tif):
            lst_real = True
            gdf_lst = gdf_units.to_crs(rasterio.open(lst_tif).crs)
            lst_vals = [
                round(float(s["mean"]), 2) if s["mean"] is not None else np.nan
                for s in zonal_stats(gdf_lst, lst_tif, stats=["mean"])
            ]
        else:
            lst_vals = [np.nan] * len(gdf_units)

        gdf_base = gdf_units.copy()
        gdf_base["Copa_pct"] = copa_pcts
        gdf_base["LST_verano_C"] = lst_vals
        gdf_base["Marginacion_idx"] = compute_marginacion(gdf_base)
        gdf_base.to_file(base_geojson, driver="GeoJSON")

        valid_lst = pd.Series(lst_vals).dropna()
        if len(valid_lst) >= 4:
            delta_icu_aire = round(float(np.clip((np.percentile(valid_lst, 90) - np.percentile(valid_lst, 25)) * 0.45, 1.2, 2.2)), 2)
        else:
            delta_icu_aire = 1.5

        summary = {
            "delta_icu_aire_c": delta_icu_aire,
            "altura_edificios_m": 6.5,
            "wc_real": wc_real,
            "lst_real": lst_real,
            "lst_escenas_compuesto": n_escenas_lst,
        }
        with open(meta_json, "w", encoding="utf-8") as f:
            json.dump(summary, f)

    df = gdf_base.copy()
    wC, wT, wS = pesos
    copa_arbol = cfg["prioridad_sombra"]["copa_arbol_adulto_m2"]

    copa_series = df["Copa_pct"].fillna(df["Copa_pct"].median() if df["Copa_pct"].notna().any() else 8.0)
    lst_series = df["LST_verano_C"].fillna(df["LST_verano_C"].median() if df["LST_verano_C"].notna().any() else 36.0)

    df["FC"] = 100.0 * (meta_copa - np.minimum(copa_series, meta_copa)) / max(meta_copa, 1.0)
    t_min, t_max = lst_series.min(), lst_series.max()
    df["FT"] = 0.0 if t_max == t_min else 100.0 * (lst_series - t_min) / (t_max - t_min)

    w_bio_sum = max(wC + wT, 1e-6)
    df["IPS_biofisico"] = np.round((wC / w_bio_sum) * df["FC"] + (wT / w_bio_sum) * df["FT"], 2)

    has_conapo = "Marginacion_idx" in df.columns and df["Marginacion_idx"].notna().any()
    if has_conapo:
        m_valid = df["Marginacion_idx"].fillna(df["Marginacion_idx"].median())
        m_min, m_max = m_valid.min(), m_valid.max()
        df["FS"] = 0.0 if m_max == m_min else 100.0 * (m_valid - m_min) / (m_max - m_min)
        df["IPS"] = np.round(wC * df["FC"] + wT * df["FT"] + wS * df["FS"], 2)
        summary["conapo_real"] = True
    else:
        df["FS"] = np.nan
        df["IPS"] = df["IPS_biofisico"]
        summary["conapo_real"] = False

    df["Lugar"] = df["IPS"].rank(ascending=False, method="min").astype(int)
    p80 = np.percentile(df["IPS"].dropna(), 80) if df["IPS"].notna().any() else 50.0
    df["Prioridad"] = np.where(
        copa_series >= meta_copa,
        "Conservación (cumple la meta)",
        np.where(df["IPS"] >= p80, "Quintil superior", "Resto"),
    )
    df["Brecha_copa_ha"] = np.round(np.maximum(0.0, (meta_copa - copa_series) / 100.0 * df["Area_ha"]), 3)
    df["Arboles_equivalentes"] = np.round(df["Brecha_copa_ha"] * 10000.0 / copa_arbol, 0).astype(int)
    df = df.sort_values("Lugar").reset_index(drop=True)

    summary["copa_media_pct"] = round(float(copa_series.mean()), 2)
    summary["lst_media_c"] = round(float(lst_series.mean()), 2)
    summary["brecha_total_ha"] = round(float(df["Brecha_copa_ha"].sum()), 2)
    summary["arboles_totales"] = int(df["Arboles_equivalentes"].sum())

    gdf_streets = None
    if os.path.exists(streets_geojson):
        try:
            gdf_streets = gpd.read_file(streets_geojson)
        except Exception:
            gdf_streets = None
    else:
        gdf_streets = fetch_fast_streets(df.head(5).geometry.union_all())
        if gdf_streets is not None and not gdf_streets.empty:
            gdf_streets.to_file(streets_geojson, driver="GeoJSON")

    summary["calles_real"] = gdf_streets is not None and not gdf_streets.empty
    return df, gdf_streets, summary