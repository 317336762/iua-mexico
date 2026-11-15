import os
import requests
import yaml

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

mun_path = "data/raw/sig/municipios_mexico.geojson"
if not os.path.exists(mun_path):
    print("Descargando polígonos municipales de México...")
    url = "https://raw.githubusercontent.com/angelnmara/geojson/master/mexicoHigh.json"
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    with open(mun_path, "wb") as f:
        f.write(r.content)
    print("Listo:", mun_path)

base_wc = "https://geodata.ucdavis.edu/cmip6/2.5m"
for model in cfg["clima"]["modelos_cmip6"]:
    for ssp in ["ssp245", "ssp585"]:
        fname = f"wc2.1_2.5m_tmax_{model}_{ssp}_2041-2060.tif"
        out_tif = os.path.join("data/raw/cmip6", fname)
        if os.path.exists(out_tif):
            continue
        print(f"Descargando {fname}...")
        resp = requests.get(f"{base_wc}/{model}/{ssp}/{fname}", stream=True, timeout=120)
        if resp.status_code == 200:
            with open(out_tif, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("Completado:", fname)
