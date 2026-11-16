import os
import yaml

DIRS = [
    "src",
    "data/raw/era5",
    "data/raw/sig",
    "data/processed/cache_municipios",
]

DEFAULT_CONFIG = {
    "proyecto": {
        "nombre": "IUA México",
        "version": "2.2-strict",
        "anio_base": 2026,
    },
    "prioridad_sombra": {
        "copa_arbol_adulto_m2": 50.0,
        "meta_copa_default_pct": 25.0,
    },
}


def init_environment():
    for d in DIRS:
        os.makedirs(d, exist_ok=True)

    init_py = os.path.join("src", "__init__.py")
    if not os.path.exists(init_py):
        with open(init_py, "w", encoding="utf-8") as f:
            f.write("")

    cfg_path = "config.yaml"
    if not os.path.exists(cfg_path):
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False, allow_unicode=True)
        print("Creado config.yaml por defecto.")
    else:
        print("config.yaml existente conservado sin modificaciones.")

    print("Estructura de directorios IUA México v2.2 verificada (módulos en src/ intactos).")


if __name__ == "__main__":
    init_environment()