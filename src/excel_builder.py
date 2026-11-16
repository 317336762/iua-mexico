import io
import math
import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def _clean_excel_val(val):
    """Convierte NaN/Inf a None para que openpyxl escriba celdas vacías reales y nunca texto 'nan'."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


def _classify_iua(tpa_val, tau_val: float) -> tuple[str | float, str]:
    """Calcula IUA y clasifica con los mismos umbrales unificados de app.py."""
    if pd.isna(tpa_val):
        return ">2100", "Baja (>2100)"
    if float(tpa_val) <= 0:
        return "Rebasado", "Rebasado"
    iua = round(float(tau_val) / float(tpa_val), 2)
    if iua >= 1.0:
        cat = "Crítica (≥ 1.00)"
    elif iua >= 0.70:
        cat = "Alta (0.70–0.99)"
    else:
        cat = "Moderada (< 0.70)"
    return iua, cat


def _style_worksheet(ws, header_row: int = 1, freeze: bool = True):
    """Aplica estilo institucional azul petróleo (#0B3C49), limpia NaN y ajusta anchos de columna."""
    fill_header = PatternFill(start_color="0B3C49", end_color="0B3C49", fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_body = Font(name="Calibri", size=10, bold=False, color="1A202C")
    thin_side = Side(border_style="thin", color="CBD5E1")
    border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for row in ws.iter_rows(min_row=header_row, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        r_idx = row[0].row
        for cell in row:
            cell.value = _clean_excel_val(cell.value)
            cell.border = border_cell
            if r_idx == header_row:
                cell.fill = fill_header
                cell.font = font_header
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            else:
                cell.font = font_body
                cell.alignment = Alignment(vertical="center")
                if (r_idx - header_row) % 2 == 0:
                    cell.fill = fill_zebra

    if freeze:
        ws.freeze_panes = f"A{header_row + 1}"

    ws.row_dimensions[header_row].height = 28

    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for row_idx in range(header_row, min(ws.max_row + 1, 200)):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 42)


def build_excel_report(
    municipio_nombre: str,
    df_ageb: pd.DataFrame,
    df_tx: pd.DataFrame,
    df_tpa: pd.DataFrame,
    limite_dias: float,
    tau_vals: tuple[float, float, float],
    cfg: dict,
    umbral_c: float | None = None,
    micro: dict | None = None,
) -> bytes:
    tau_arb, tau_cor, tau_ban = tau_vals
    anio_base = cfg.get("proyecto", {}).get("anio_base", 2026)

    # 1. Matriz completa de sensibilidad (12 combinaciones: 6 escenarios-percentiles x Sin/Con ICU)
    sens_rows = []
    for _, r in df_tpa.iterrows():
        for condicion, col_tse, col_tpa in [
            ("Sin Isla de Calor (Regional)", "TSE_regional", "TpA_anios"),
            ("Con Isla de Calor (Urbano)", "TSE_con_ICU", "TpA_con_ICU"),
        ]:
            tse_v = r[col_tse]
            tpa_v = r[col_tpa]
            iua_a, cat_a = _classify_iua(tpa_v, tau_arb)
            iua_c, _ = _classify_iua(tpa_v, tau_cor)
            iua_b, _ = _classify_iua(tpa_v, tau_ban)

            sens_rows.append({
                "Municipio": municipio_nombre,
                "Escenario_CMIP6": r["Escenario"],
                "Percentil": r["Percentil"],
                "Condicion_Termica": condicion,
                "Tasa_Calentamiento_C_anio": _clean_excel_val(r["r_tendencia_C_anio"]),
                "Adelanto_ICU_anios": 0.0 if "Sin" in condicion else _clean_excel_val(r["Adelanto_ICU_anios"]),
                "TsE_Anio_Sin_Precedentes": int(round(float(tse_v))) if pd.notna(tse_v) else ">2100",
                "TpA_Ventana_Adaptacion_anios": round(float(tpa_v), 1) if pd.notna(tpa_v) else ">2100",
                "IUA_Arbolado": iua_a,
                "Clasificacion_Urgencia_Arbolado": cat_a,
                "IUA_Infraestructura_Lineal": iua_c,
                "IUA_Banquetas_Peatonales": iua_b,
            })

    df_sensibilidad = pd.DataFrame(sens_rows)

    # 2. Limpieza de tabla AGEB real y fila de totales (NaN -> None)
    df_ageb_clean = df_ageb.drop(columns=["geometry"], errors="ignore").copy()
    df_ageb_clean = df_ageb_clean.map(_clean_excel_val)

    total_arboles = int(df_ageb["Arboles_equivalentes"].fillna(0).sum()) if "Arboles_equivalentes" in df_ageb.columns else 0
    n_ageb_total = len(df_ageb_clean)
    n_quintil_sup = int((df_ageb["Prioridad"] == "Quintil superior").sum()) if "Prioridad" in df_ageb.columns else 0
    copa_prom_ageb = (
        round(float(df_ageb["Copa_pct"].dropna().mean()), 2)
        if "Copa_pct" in df_ageb.columns and df_ageb["Copa_pct"].notna().any()
        else None
    )

    df_tx_clean = df_tx.map(_clean_excel_val)

    # 3. Hoja de Resumen Ejecutivo y Trazabilidad Metodológica
    n_escenas_lst = int(micro.get("lst_escenas_compuesto", 0)) if micro else 0
    meta_rows = [
        ("DIAGNÓSTICO MUNICIPAL", municipio_nombre, "Identificador territorial evaluado"),
        ("Año base del diagnóstico", anio_base, "Configuración en config.yaml (proyecto.anio_base)"),
        ("Umbral de calor extremo aplicado (°C)", umbral_c if umbral_c is not None else "Percentil 95 local (ver panel)", "Temperatura máxima diaria sobre la cual se contabilizan días extremos"),
        ("Máximo histórico de referencia 1981–2010 (días/año)", limite_dias, "Línea base para determinar el Tiempo sin Precedentes (TsE)"),
        ("Supuesto τ — Arbolado de alineación (años)", tau_arb, "Tiempo editable para consolidar sombra funcional"),
        ("Supuesto τ — Infraestructura verde lineal (años)", tau_cor, "Tiempo editable para corredores verdes"),
        ("Supuesto τ — Cruces y banquetas peatonales (años)", tau_ban, "Tiempo editable para arbolado peatonal"),
        ("Total de unidades urbanas (AGEB) evaluadas", n_ageb_total, "Calculado sobre geometrías reales en hoja Prioridad_Sombra"),
        ("AGEB en Quintil Superior de prioridad", n_quintil_sup, "Unidades con mayor déficit de copa, calor superficial y vulnerabilidad"),
        ("Cobertura de copa promedio en AGEB (%)", copa_prom_ageb if copa_prom_ageb is not None else "N/D", "Promedio exclusivo de las AGEB urbanas evaluadas"),
        ("Cobertura de copa total municipal (%)", micro["copa_media_pct"] if micro else "Ver tablero", "Incluye áreas naturales/serranas dentro del límite municipal"),
        ("Escenas Landsat 8/9 válidas en compuesto LST", n_escenas_lst if micro else "Ver tablero", "Mínimo normativo requerido: 3 escenas estivales con máscara QA_PIXEL"),
        ("Delta Isla de Calor Urbana estimado (°C)", f"+{micro['delta_icu_aire_c']}" if micro else "Ver tablero", "Diferencia térmica urbano-rural estimada por teledetección"),
        ("Déficit arbóreo total acumulado (árboles)", total_arboles, "Suma real de árboles requeridos en las AGEB por debajo de la meta"),
        ("NOTA METODOLÓGICA — Índices estándar", "TsE (Mora et al., 2013), TX95p, R99p, WBT (Stull, 2011; umbral IUA ≥ 28 °C)", "Métricas climáticas estándar OMM / ETCCDI y umbral operativo IUA"),
        ("NOTA METODOLÓGICA — Constructos IUA", "TpA = TsE_urbano - Año_base | IUA = τ / TpA", "Operacionalización propia para planificación municipal"),
    ]
    df_meta = pd.DataFrame(meta_rows, columns=["Concepto / Indicador", "Valor", "Fuente / Criterio Técnico"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_meta.to_excel(writer, sheet_name="Resumen_Metodologia", index=False)
        df_sensibilidad.to_excel(writer, sheet_name="TpA_y_Sensibilidad", index=False)
        df_ageb_clean.to_excel(writer, sheet_name="Prioridad_Sombra", index=False)
        df_tx_clean.to_excel(writer, sheet_name="Serie_TX", index=False)

        wb = writer.book
        for sheet_name in ["Resumen_Metodologia", "TpA_y_Sensibilidad", "Prioridad_Sombra", "Serie_TX"]:
            _style_worksheet(wb[sheet_name], header_row=1, freeze=True)

        ws_ageb = wb["Prioridad_Sombra"]
        if n_ageb_total > 0 and "Arboles_equivalentes" in df_ageb_clean.columns:
            tot_row = ws_ageb.max_row + 1
            col_arb_idx = list(df_ageb_clean.columns).index("Arboles_equivalentes") + 1
            ws_ageb.cell(row=tot_row, column=1, value="TOTAL DÉFICIT URBANO (AGEB)").font = Font(name="Calibri", size=10, bold=True, color="0B3C49")
            tot_cell = ws_ageb.cell(row=tot_row, column=col_arb_idx, value=total_arboles)
            tot_cell.font = Font(name="Calibri", size=10, bold=True, color="0B3C49")
            tot_cell.number_format = "#,##0"
            fill_tot = PatternFill(start_color="E6F2F5", end_color="E6F2F5", fill_type="solid")
            for c_i in range(1, ws_ageb.max_column + 1):
                ws_ageb.cell(row=tot_row, column=c_i).fill = fill_tot

    output.seek(0)
    return output.getvalue()