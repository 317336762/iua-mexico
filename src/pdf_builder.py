import io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def _draw_demo_watermark(canvas, doc):
    """Estampa marca de agua diagonal cuando el reporte se genera en Modo Demostración."""
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 36)
    canvas.setFillColor(colors.Color(0.85, 0.25, 0.15, alpha=0.14))
    canvas.translate(letter[0] / 2.0, letter[1] / 2.0)
    canvas.rotate(42)
    canvas.drawCentredString(0, 18, "VISTA DE DEMOSTRACIÓN")
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawCentredString(0, -14, "CIFRAS ILUSTRATIVAS — NO VÁLIDO PARA USO NORMATIVO")
    canvas.restoreState()


def build_executive_pdf(
    municipio_nombre: str,
    resumen: dict,
    tpa_val: float | None,
    tse_val: float | str,
    iua_val: str,
    umbral_c: float | None = None,
    meta_copa: int = 20,
    tau_arb: float = 9.5,
    anio_base: int = 2026,
    wbt_max: float | None = None,
    dias_wbt28: float | None = None,
    p99_lluvia: float | None = None,
    respaldo_activo: bool = False,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=32,
        bottomMargin=30,
    )
    story = []

    PETROL_DARK = colors.HexColor("#0B3C49")
    PETROL_LIGHT = colors.HexColor("#E6F2F5")
    TEXT_DARK = colors.HexColor("#1A202C")
    TEXT_MUTED = colors.HexColor("#4A5568")
    BORDER_LIGHT = colors.HexColor("#CBD5E1")
    ZEBRA_BG = colors.HexColor("#F8FAFC")
    WARN_BG = colors.HexColor("#FEF3C7")
    WARN_BORDER = colors.HexColor("#B45309")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15.5,
        textColor=PETROL_DARK,
        spaceAfter=3,
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=TEXT_MUTED,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "HeadingStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        textColor=PETROL_DARK,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.7,
        textColor=TEXT_DARK,
        leading=12,
    )
    banner_style = ParagraphStyle(
        "BannerStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=PETROL_DARK,
        leading=12.5,
    )
    kpi_label_style = ParagraphStyle(
        "KpiLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.3,
        textColor=TEXT_MUTED,
        leading=9,
    )
    kpi_val_style = ParagraphStyle(
        "KpiVal",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.0,
        textColor=PETROL_DARK,
        leading=14,
    )
    method_style = ParagraphStyle(
        "MethodStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.3,
        textColor=TEXT_MUTED,
        leading=9.8,
    )

    copa_mun = resumen.get("copa_media_pct", 0)
    lst_c = resumen.get("lst_media_c", 0)
    delta_icu_aire = float(resumen.get("delta_icu_aire_c", 0))
    delta_tmax_diurno = round(0.25 * delta_icu_aire, 2)
    arboles = int(resumen.get("arboles_totales", 0))
    brecha_ha = round(float(resumen.get("brecha_total_ha", 0)), 1)
    conapo_real = resumen.get("conapo_real", True)

    es_post_2100 = str(tse_val).strip() == ">2100" or (tpa_val is None and str(tse_val).strip() == ">2100")
    tpa_rebasado = (not es_post_2100) and (tpa_val is None or float(tpa_val) <= 0)
    horizonte_max = max(2100 - int(anio_base), 1)

    if es_post_2100:
        tse_disp = ">2100"
        tpa_texto = f">{horizonte_max} años (posterior a 2100)"
        kpi_tpa_corto = f">2100 (>{horizonte_max} a)"
    elif tpa_rebasado:
        tse_disp = f"{int(round(float(tse_val)))}" if isinstance(tse_val, (int, float)) else str(tse_val)
        tpa_texto = "Rebasado (<= 0 años)"
        kpi_tpa_corto = f"{tse_disp} (Rebasado)"
    else:
        tse_disp = f"{int(round(float(tse_val)))}" if isinstance(tse_val, (int, float)) else str(tse_val)
        tpa_texto = f"{float(tpa_val):.1f} años"
        kpi_tpa_corto = f"{tse_disp} ({float(tpa_val):.1f} años)"

    umbral_texto = f">{umbral_c} °C (TX95p)" if umbral_c is not None else "Percentil 95 local (TX95p)"

    # 1. Encabezado institucional
    story.append(Paragraph("FICHA EJECUTIVA MUNICIPAL — CLIMA Y ADAPTACIÓN URBANA", title_style))
    story.append(
        Paragraph(
            f"<b>Municipio:</b> {municipio_nombre}  |  <b>Año base:</b> {anio_base}  |  "
            f"<b>Trayectoria de referencia:</b> CMIP6 SSP5-8.5 (Mediana P50)",
            subtitle_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.8, color=PETROL_DARK, spaceAfter=8))

    if respaldo_activo:
        warn_tbl = Table(
            [[Paragraph(
                "<b>MODO DEMOSTRACIÓN / GOBERNANZA DE DATOS:</b> Este documento incluye series ilustrativas o carece de algún insumo local verificado. "
                "No utilizar como dictamen normativo ni soporte único de obra pública.",
                ParagraphStyle("Warn", parent=body_style, fontSize=8, textColor=colors.HexColor("#78350F")),
            )]],
            colWidths=[540],
        )
        warn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
            ("LINEBEFORE", (0, 0), (0, -1), 3.5, WARN_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(warn_tbl)
        story.append(Spacer(1, 6))

    # 2. Banner de Semáforo de Urgencia
    banner_txt = (
        f"<b>SEMÁFORO DE URGENCIA ADAPTATIVA (LÍNEA BASE REGIONAL) — {iua_val}</b><br/>"
        f"Ventana operativa regional de adaptación (TpA): <b>{tpa_texto}</b> frente a un tiempo estimado de consolidación vegetal "
        f"de <b>tau = {tau_arb} años</b> para alcanzar cobertura de copa funcional."
    )
    banner_tbl = Table([[Paragraph(banner_txt, banner_style)]], colWidths=[540])
    banner_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PETROL_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 4.0, PETROL_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(banner_tbl)
    story.append(Spacer(1, 8))

    # 3. Tarjetas KPI resumen
    wbt_str = f"{wbt_max:.1f} °C ({dias_wbt28:.1f} d/año)" if (wbt_max is not None and dias_wbt28 is not None) else "Ver serie ERA5"
    rain_str = f"R99p > {p99_lluvia} mm" if p99_lluvia is not None else "Percentil 99 local"

    kpi_cells = [[
        Paragraph("Cobertura Arbórea Total (Mun.)*", kpi_label_style),
        Paragraph("LST Estival / Sensib. +Delta ICU", kpi_label_style),
        Paragraph("TsE Regional / Ventana TpA", kpi_label_style),
        Paragraph("Extremos Húmedo y Pluvial", kpi_label_style),
    ], [
        Paragraph(f"{copa_mun}%", kpi_val_style),
        Paragraph(f"{lst_c} °C (+{delta_icu_aire} °C)", kpi_val_style),
        Paragraph(kpi_tpa_corto, kpi_val_style),
        Paragraph(f"WBT {wbt_max:.1f}°C | {p99_lluvia}mm" if (wbt_max and p99_lluvia) else wbt_str, kpi_val_style),
    ]]
    kpi_tbl = Table(kpi_cells, colWidths=[135, 135, 135, 135])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA_BG),
        ("BOX", (0, 0), (0, -1), 0.6, BORDER_LIGHT),
        ("BOX", (1, 0), (1, -1), 0.6, BORDER_LIGHT),
        ("BOX", (2, 0), (2, -1), 0.6, BORDER_LIGHT),
        ("BOX", (3, 0), (3, -1), 0.6, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 4))

    # 4. Diagnóstico Climático y Exposición Térmica Urbana
    story.append(Paragraph("1. Diagnóstico de Exposición Climática y Sensibilidad por Isla de Calor", heading_style))
    diag_text = (
        f"El análisis geoespacial registra una cobertura arbórea promedio de <b>{copa_mun}%</b> sobre el límite municipal total "
        f"y una Temperatura Superficial Terrestre (LST) estival mediana de <b>{lst_c} °C</b> (compuesto Landsat 8/9 con máscara QA_PIXEL). "
        f"Bajo la línea base regional observada (Reanálisis ERA5 vía Open-Meteo 1950–2024 + anomalías CMIP6 SSP5-8.5 P50) y el umbral local "
        f"<b>{umbral_texto}</b>, el Tiempo sin Precedentes (<i>Climate Departure</i>) se proyecta en <b>TsE ~ {tse_disp}</b> (<b>TpA = {tpa_texto}</b>). "
        f"Como análisis de sensibilidad urbana, un incremento atmosférico estimado de <b>+{delta_icu_aire} °C</b> por Isla de Calor "
        f"(equivalente a <b>+{delta_tmax_diurno} °C</b> diurnos; Voogt & Oke, 2003; Mildrexler et al., 2011; Oke et al., 2017) adelanta dicho umbral en las zonas densas."
    )
    story.append(Paragraph(diag_text, body_style))
    story.append(Spacer(1, 4))

    # 5. Metas Físicas de Mitigación
    story.append(Paragraph("2. Metas Físicas de Infraestructura Verde y Mitigación Térmica", heading_style))

    tbl_header_style = ParagraphStyle(
        "TblHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.3,
        textColor=colors.white,
        leading=10.5,
    )
    tbl_cell_style = ParagraphStyle(
        "TblCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.2,
        textColor=TEXT_DARK,
        leading=10.5,
    )
    tbl_bold_style = ParagraphStyle(
        "TblBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.2,
        textColor=PETROL_DARK,
        leading=10.5,
    )

    criterio_ips_txt = (
        "Focalización multicriterio por déficit de copa, LST estival y marginación CONAPO"
        if conapo_real
        else "Focalización biofísica (copa + LST renormalizados; sin capa CONAPO, no comparable entre municipios)"
    )

    inv_data = [
        [
            Paragraph("Componente de Adaptación", tbl_header_style),
            Paragraph("Meta Física Estimada", tbl_header_style),
            Paragraph("Mecanismo Físico y Objetivo Climático", tbl_header_style),
        ],
        [
            Paragraph("Arbolado Urbano de Alineación", tbl_cell_style),
            Paragraph(f"{arboles:,} árboles nativos", tbl_cell_style),
            Paragraph(f"Cierre del déficit en unidades urbanas por debajo de la meta ({meta_copa}% de copa)", tbl_cell_style),
        ],
        [
            Paragraph("Superficie de Dosel Requerida", tbl_cell_style),
            Paragraph(f"{brecha_ha:,.1f} hectáreas", tbl_cell_style),
            Paragraph("Intercepción solar y reducción de Temperatura Radiante Media (Tmrt) peatonal", tbl_cell_style),
        ],
        [
            Paragraph("Consolidación Vegetal (tau)", tbl_cell_style),
            Paragraph(f"{tau_arb} años (supuesto)", tbl_cell_style),
            Paragraph(f"Establecimiento a copa funcional frente a ventana disponible ({tpa_texto})", tbl_cell_style),
        ],
        [
            Paragraph("ENFOQUE PRIORITARIO", tbl_bold_style),
            Paragraph("Quintil Superior (AGEB)", tbl_bold_style),
            Paragraph(criterio_ips_txt, tbl_bold_style),
        ],
    ]
    t = Table(inv_data, colWidths=[145, 135, 260])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PETROL_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ZEBRA_BG]),
        ("BACKGROUND", (0, -1), (-1, -1), PETROL_LIGHT),
    ]))
    story.append(t)
    story.append(Spacer(1, 4))

    # 6. Plan de Acción
    story.append(Paragraph("3. Lineamientos de Intervención para Cabildo y Obras Públicas", heading_style))
    acciones = (
        f"• <b>Infraestructura Verde Focalizada:</b> Concentrar el suministro y plantación de los <b>{arboles:,} árboles nativos</b> "
        f"exclusivamente en las unidades urbanas con déficit respecto a la meta del {meta_copa}%, empleando especies adaptadas de bajo requerimiento hídrico.<br/>"
        "• <b>Mitigación Térmica en Corredores Peatonales (AbE):</b> Priorizar arborización lineal en banquetas y camellones dentro de las unidades "
        "que alcanzan primero el TsE, reduciendo la carga térmica radiante (Tmrt) y el estrés por bulbo húmedo (WBT >= 28 °C).<br/>"
        f"• <b>Gestión Azul-Verde y Drenaje Sostenible (SUDS):</b> Implementar jardines de lluvia, alcorques inundables y pavimentos permeables en las unidades "
        f"del Quintil Superior donde coinciden islas de calor y recurrencia de precipitación extrema ({rain_str})."
    )
    story.append(Paragraph(acciones, body_style))
    story.append(Spacer(1, 8))

    # 7. Bloque de Trazabilidad Metodológica y Gobernanza
    method_txt = (
        "<b>TRAZABILIDAD METODOLÓGICA, VERSIONADO Y FUENTES DE DATOS (v2.0-strict)</b><br/>"
        "• <b>Estándares científicos empleados:</b> Reanálisis climático ERA5 vía Open-Meteo (1950–2024); anomalías multimodelo CMIP6 (WorldClim 2.1: ACCESS-CM2, "
        "MPI-ESM1-2-HR, MRI-ESM2-0); cobertura arbórea ESA WorldCover (10 m); compuesto multitemporal de Temperatura Superficial Terrestre Landsat 8/9 "
        "(enmascaramiento QA_PIXEL); red vial OpenStreetMap; indicadores sociodemográficos CONAPO/INEGI. Definición de <i>Tiempo sin Precedentes (TsE)</i> "
        "según Mora et al. (2013) sobre línea base 1981–2010; índices de extremos OMM/ETCCDI (TX95p, R99p) y umbral WBT >= 28 °C (Sherwood & Huber, 2010; Stull, 2011).<br/>"
        "• <b>Constructos operativos y capas de emulación IUA México:</b> Trayectorias anuales emuladas a partir de anomalías CMIP6 + tendencia local ERA5; "
        "parametrización empírica de cribado Delta ICU (Voogt & Oke, 2003; Mildrexler et al., 2011); <i>Tiempo para Actuar (TpA = TsE - Año_base)</i> e "
        "<i>Índice de Urgencia Adaptativa (IUA = tau / TpA)</i>."
    )
    method_tbl = Table([[Paragraph(method_txt, method_style)]], colWidths=[540])
    method_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(method_tbl)
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "IUA México v2.0 — Desarrollado por Baruc Martínez Velasco | Contacto técnico: martinezbaruc13@gmail.com",
            ParagraphStyle("Footer", parent=styles["Normal"], fontName="Helvetica", fontSize=7, textColor=TEXT_MUTED),
        )
    )

    if respaldo_activo:
        doc.build(story, onFirstPage=_draw_demo_watermark, onLaterPages=_draw_demo_watermark)
    else:
        doc.build(story)

    buffer.seek(0)
    return buffer.getvalue()