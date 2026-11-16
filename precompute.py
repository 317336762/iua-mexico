import os
import geopandas as gpd
import numpy as np
import rasterio
from rasterstats import zonal_stats

os.makedirs("data/processed", exist_ok=True)
os.makedirs("data/raw/sig", exist_ok=True)


def run_precompute():
    mun_path = "data/raw/sig/municipios_mexico.geojson"
    if not os.path.exists(mun_path):
        raise FileNotFoundError(f"No se encontró el catálogo municipal en {mun_path}")

    print("1. Optimizando geometrías municipales (WGS84 simplificado)...")
    gdf_mun = gpd.read_file(mun_path)
    if gdf_mun.crs is None:
        gdf_mun = gdf_mun.set_crs("EPSG:4326")
    else:
        gdf_mun = gdf_mun.to_crs("EPSG:4326")

    gdf_light = gdf_mun.copy()
    gdf_light["geometry"] = gdf_light.geometry.simplify(0.001, preserve_topology=True)

    # Cómputo estricto únicamente con insumos raster reales si están disponibles en disco
    wc_vrt = "data/raw/sig/worldcover_mexico.tif"
    if os.path.exists(wc_vrt):
        print("2. Calculando cobertura arbórea municipal real desde ESA WorldCover...")
        gdf_wc = gdf_mun.to_crs(rasterio.open(wc_vrt).crs)
        copa_vals = []
        for st in zonal_stats(gdf_wc, wc_vrt, categorical=True):
            tot = sum(v for k, v in st.items() if k != 0)
            copa_vals.append(round((st.get(10, 0) / tot * 100.0) if tot > 0 else np.nan, 2))
        gdf_light["copa_arborea_pct"] = copa_vals
    else:
        print("2. Omitiendo métricas biofísicas globales (sin raster nacional en disco; se calculan bajo demanda).")

    out_mun = "data/processed/municipios_mexico_opt.parquet"
    gdf_light.to_parquet(out_mun)
    print(f"   -> Guardado: {out_mun} ({len(gdf_light)} municipios)")

    vial_shp = "data/raw/sig/red_vial_inegi.shp"
    if os.path.exists(vial_shp):
        print("3. Optimizando Red Nacional de Caminos...")
        gdf_vial = gpd.read_file(vial_shp).to_crs("EPSG:4326")
        gdf_vial["geometry"] = gdf_vial.geometry.simplify(0.0005)
        gdf_vial.to_parquet("data/processed/red_vial_opt.parquet")
        print("   -> Red vial optimizada en Parquet.")


if __name__ == "__main__":
    run_precompute()