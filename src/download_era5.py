import os
import yaml
import cdsapi

with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

BBOX = cfg["proyecto"]["bbox_nacional"]
OUT_DIR = "data/raw/era5"
QUARTERS = {"Q1": ["01", "02", "03"], "Q2": ["04", "05", "06"], "Q3": ["07", "08", "09"], "Q4": ["10", "11", "12"]}

client = cdsapi.Client()
for year in range(1981, 2021):
    for q_name, months in QUARTERS.items():
        target = os.path.join(OUT_DIR, f"era5_mx_{year}_{q_name}.nc")
        if os.path.exists(target):
            continue
        print(f"[{year}-{q_name}] Descargando ERA5-Land Nacional...")
        client.retrieve(
            "reanalysis-era5-land",
            {
                "variable": ["2m_temperature"],
                "year": str(year),
                "month": months,
                "day": [f"{d:02d}" for d in range(1, 32)],
                "time": ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"],
                "area": BBOX,
                "data_format": "netcdf",
                "download_format": "unarchived",
            },
            target,
        )
