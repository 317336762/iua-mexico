import io
import os
import openpyxl
import pandas as pd


def export_filled_template(
    template_path: str,
    df_ageb: pd.DataFrame,
    df_tx: pd.DataFrame,
    df_tpa: pd.DataFrame,
    delta_icu: float,
    limite_dias: float,
    umbral_tx: float,
    anio_base: int = 2026,
) -> bytes:
    if os.path.exists(template_path):
        wb = openpyxl.load_workbook(template_path)
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "TpA"

    if "Prioridad_sombra" in wb.sheetnames:
        ws_ps = wb["Prioridad_sombra"]
        ws_ps["C11"] = "Empíricos"
        for idx, row in df_ageb.head(1000).iterrows():
            r = 16 + idx
            ws_ps[f"A{r}"] = row["Clave_AGEB"]
            ws_ps[f"B{r}"] = row["Colonia_Ref"]
            ws_ps[f"C{r}"] = float(row["Area_ha"])
            ws_ps[f"D{r}"] = float(row["Copa_pct"])
            ws_ps[f"E{r}"] = float(row["LST_verano_C"])
            ws_ps[f"F{r}"] = float(row["Marginacion_idx"])

    if "Serie_TX" in wb.sheetnames:
        ws_tx = wb["Serie_TX"]
        cols_map = {
            "Ref_historica": "C",
            "SSP2-4.5 P10": "D",
            "SSP2-4.5 P50 (mediana)": "E",
            "SSP2-4.5 P90": "F",
            "SSP5-8.5 P10": "G",
            "SSP5-8.5 P50 (mediana)": "H",
            "SSP5-8.5 P90": "I",
        }
        for idx, row in df_tx.iterrows():
            r = 17 + idx
            for col_name, col_let in cols_map.items():
                val = row.get(col_name)
                if pd.notna(val):
                    ws_tx[f"{col_let}{r}"] = float(val)

    if "TpA" in wb.sheetnames:
        ws_tpa = wb["TpA"]
        ws_tpa["C4"] = int(anio_base)
        ws_tpa["C5"] = float(delta_icu)
        ws_tpa["C6"] = float(limite_dias)
        ws_tpa["C7"] = float(umbral_tx)
        for idx, row in df_tpa.iterrows():
            r = 9 + idx
            if pd.notna(row["TSE_regional"]):
                ws_tpa[f"D{r}"] = int(row["TSE_regional"])
            ws_tpa[f"F{r}"] = float(row["r_tendencia_C_anio"])
            ws_tpa[f"J{r}"] = "Calculado automáticamente (ERA5-Land + CMIP6 + LST Landsat)"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
