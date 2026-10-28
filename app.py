import io
import re
import zipfile
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
import streamlit as st

import engine  # Módulo del motor auxiliar de backend
from parsers import parse_cfg_content, parse_cos_content, parse_spc_content

st.set_page_config(
    page_title="ATFCM Sector & Configuration Analyzer",
    page_icon="✈️",
    layout="wide",
)

# Inicializar sesión para almacenar estados y exportaciones
if "uploaded_cos" not in st.session_state:
    st.session_state.uploaded_cos = []
if "uploaded_spc" not in st.session_state:
    st.session_state.uploaded_spc = []
if "uploaded_cfg" not in st.session_state:
    st.session_state.uploaded_cfg = []
if "last_zip_buffer" not in st.session_state:
    st.session_state.last_zip_buffer = None
if "last_cfg_content" not in st.session_state:
    st.session_state.last_cfg_content = ""


def render_tab1():
    st.header("1. Carga de Archivos de Entrada (.COS, .SPC, .CFG)")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** El punto de entrada y repositorio de datos maestros para la sesión de análisis.
        * **Datos requeridos:** 
          * Ficheros de Esquema de Apertura (`.COS` / `.txt`).
          * Definición geométrica y jerárquica de sectores (`.SPC` / `.txt`).
          * Catálogo de configuraciones operativas (`.CFG` / `.txt`).
        * **Interacción del usuario:** Carga mediante explorador de archivos con soporte multi-archivo. El sistema valida automáticamente la persistencia en sesión.
        """)
    
    st.markdown("---")

    col_cos, col_spc, col_cfg = st.columns(3)

    with col_cos:
        st.subheader("📄 Archivos .COS")
        uploaded_cos = st.file_uploader(
            "Esquemas de Apertura (.COS):",
            type=["cos", "txt"],
            accept_multiple_files=True,
            key="uploader_cos",
        )
        if uploaded_cos:
            st.session_state.uploaded_cos = uploaded_cos
            st.success(f"Cargados: {len(uploaded_cos)} .COS")

    with col_spc:
        st.subheader("🧩 Archivos .SPC")
        uploaded_spc = st.file_uploader(
            "Definición de Sectores (.SPC):",
            type=["spc", "txt"],
            accept_multiple_files=True,
            key="uploader_spc",
        )
        if uploaded_spc:
            st.session_state.uploaded_spc = uploaded_spc
            st.success(f"Cargados: {len(uploaded_spc)} .SPC")

    with col_cfg:
        st.subheader("⚙️ Archivos .CFG")
        uploaded_cfg = st.file_uploader(
            "Definición de Configuraciones (.CFG):",
            type=["cfg", "txt"],
            accept_multiple_files=True,
            key="uploader_cfg",
        )
        if uploaded_cfg:
            st.session_state.uploaded_cfg = uploaded_cfg
            st.success(f"Cargados: {len(uploaded_cfg)} .CFG")


def obtener_numero_sectores_nominal(cnf_nombre):
    match = re.search(r'CNF(\d+)', str(cnf_nombre).upper())
    if match:
        return int(match.group(1))
    return 1


def clasificar_sector(sector_name, cs_hierarchy=None):
    if cs_hierarchy:
        if sector_name in cs_hierarchy:
            return "CS"
        for es_list in cs_hierarchy.values():
            if sector_name in es_list:
                return "ES"
                
    if any(sector_name.endswith(str(i)) for i in range(10)):
        return "ES"
    return "CS"


def calcular_minutos_tramo(h_ini, h_fin):
    """Calcula la duración en minutos entre dos cadenas de hora HH:MM."""
    try:
        p_ini = [int(x) for x in h_ini.strip().split(":")]
        p_fin = [int(x) for x in h_fin.strip().split(":")]
        min_ini = p_ini[0] * 60 + p_ini[1]
        min_fin = p_fin[0] * 60 + p_fin[1]
        diff = min_fin - min_ini
        if diff < 0:  # Cruce de medianoche
            diff += 24 * 60
        return diff if diff > 0 else 30
    except Exception:
        return 30


def render_tab2():
    st.header("2. Dashboard de Exploración y Análisis del ACC")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** Centro de control analítico para evaluar curvas de apertura cronológica, dinámicas de desdoblamiento, diagramas de Gantt y modelos predictivos de tráfico.
        * **Datos requeridos:** Ficheros `.COS`, `.SPC` y `.CFG` previamente cargados en la Pestaña 1.
        * **Interacción del usuario:** Selección de sub-enfoques mediante botones de radio y filtrado dinámico por Centro ACC, Fecha del Plan, Turno Operativo y Tipo de Sector.
        """)
    
    st.markdown("---")

    if "uploaded_cos" not in st.session_state or not st.session_state.uploaded_cos:
        st.warning("⚠️ Por favor, carga los archivos .COS en la Pestaña 1 para habilitar la exploración.")
        return

    all_dfs = []
    files_cos = st.session_state.uploaded_cos
    if not isinstance(files_cos, list): 
        files_cos = [files_cos]

    for cos_file in files_cos:
        try:
            content_bytes = cos_file.getvalue() if hasattr(cos_file, "getvalue") else cos_file
            content_lines = content_bytes.decode('latin-1', errors='ignore').splitlines()
            rows = []
            for line in content_lines:
                p = line.split(";")
                if len(p) >= 5:
                    rows.append({
                        "Fecha": p[0].strip(),
                        "ACC": p[1].strip().upper(),
                        "Hora": p[2].strip(),
                        "Hora_Fin": p[3].strip(),
                        "Configuracion": p[4].strip().upper()
                    })
            df_parsed = pd.DataFrame(rows)
            if not df_parsed.empty:
                df_parsed["Archivo"] = getattr(cos_file, "name", "archivo.cos")
                all_dfs.append(df_parsed)
        except Exception as e:
            st.error(f"Error procesando archivo: {e}")
            
    df_base = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

    if df_base.empty:
        st.error("🚨 Los archivos cargados no pudieron ser procesados.")
        return

    if "Turno" not in df_base.columns:
        df_base["Turno"] = df_base["Hora"].apply(engine.get_shift)
        
    if "Duracion_Min" not in df_base.columns:
        df_base["Duracion_Min"] = [calcular_minutos_tramo(row["Hora"], row["Hora_Fin"]) for _, row in df_base.iterrows()]

    cfg_files_list = st.session_state.get("uploaded_cfg", None)
    full_map = engine.build_cfg_map(cfg_files_list) if cfg_files_list and hasattr(engine, "build_cfg_map") else {}
    
    cs_hierarchy = {}
    if st.session_state.uploaded_spc and hasattr(engine, "get_acc_cs_mapping"):
        try:
            _, cs_hierarchy = engine.get_acc_cs_mapping(
                st.session_state.uploaded_spc,
                cfg_files=st.session_state.get("uploaded_cfg"),
                cos_files=st.session_state.get("uploaded_cos")
            )
        except Exception:
            pass

    def calcular_sectores_activos(cnf):
        cnf_str = str(cnf).upper().strip()
        if full_map and cnf_str in full_map: 
            return len(full_map[cnf_str])
        match = re.match(r"^(\d+)", cnf_str)
        return int(match.group(1)) if match else 1

    df_base["Sectores_Activos"] = df_base["Configuracion"].apply(calcular_sectores_activos)

    sub_tab = st.radio(
        "Selecciona el enfoque de análisis:",
        options=[
            "📊 2.1 Análisis Global del ACC", 
            "🔄 2.2 Dinámica de Sectores Colapsados / Desdoblados",
            "🗺️ 2.3 Gantt de Sectores Activos",
            "🔮 2.4 Asistente Predictivo de Capacidad"
        ],
        horizontal=True,
        key="sub_tab_selector"
    )
    st.markdown("---")

    st.markdown("### 🔍 Filtros de Selección de Escenario")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        acc_sel = st.selectbox("Seleccionar Centro ACC:", options=sorted(list(df_base["ACC"].unique())), key="global_acc_sel")
    
    fechas_disponibles = sorted(list(df_base[df_base["ACC"] == acc_sel]["Fecha"].unique()))
    with f_col2:
        fecha_sel = st.selectbox("Seleccionar Fecha del Plan:", options=["TODOS LOS DÍAS (Agregado)"] + fechas_disponibles, key="global_fecha_sel")
        
    with f_col3:
        turno_sel = st.selectbox("Filtrar por Turno:", options=["TODOS", "Mañana", "Tarde", "Noche"], key="global_turno_sel")

    with f_col4:
        tipo_sector_sel = st.selectbox(
            "Filtrar Tipo de Sector:",
            options=["TODOS (CS y ES)", "Solo Sectores Integrados (CS)", "Solo Sectores Elementales (ES)"],
            key="global_tipo_sector_sel"
        )

    if fecha_sel == "TODOS LOS DÍAS (Agregado)":
        df_filtered = df_base[df_base["ACC"] == acc_sel].copy()
    else:
        df_filtered = df_base[(df_base["ACC"] == acc_sel) & (df_base["Fecha"] == fecha_sel)].copy()
        
    if turno_sel != "TODOS":
        df_filtered = df_filtered[df_filtered["Turno"] == turno_sel]

    if df_filtered.empty:
        st.info("No hay registros para la combinación de filtros seleccionada.")
        return

    if "2.1" in sub_tab:
        dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel, df_base, full_map, cs_hierarchy, tipo_sector_sel)
    elif "2.2" in sub_tab:
        dibujar_subtab_22_colapsados(df_filtered, full_map, acc_sel, fecha_sel, turno_sel)
    elif "2.3" in sub_tab:
        dibujar_subtab_23_gantt_sectores(df_filtered, full_map, fecha_sel, cs_hierarchy)
    elif "2.4" in sub_tab:
        dibujar_subtab_24_predictivo(df_filtered, full_map, fecha_sel)


def dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel, df_base, full_map, cs_hierarchy, tipo_sector_sel):
    st.subheader("⏱️ Perfil de Carga y Capacidad Cronológica del ACC")

    df_plot = df_filtered.copy()

    if tipo_sector_sel != "TODOS (CS y ES)":
        def contar_sectores_filtrados(cnf):
            sectores_cnf = full_map.get(str(cnf).upper().strip(), set())
            if not sectores_cnf:
                return obtener_numero_sectores_nominal(cnf)
            if "CS" in tipo_sector_sel:
                return sum(1 for s in sectores_cnf if clasificar_sector(s, cs_hierarchy) == "CS")
            else:
                return sum(1 for s in sectores_cnf if clasificar_sector(s, cs_hierarchy) == "ES")

        df_plot["Sectores_Activos"] = df_plot["Configuracion"].apply(contar_sectores_filtrados)
    else:
        df_plot["Sectores_Activos"] = df_plot["Configuracion"].apply(
            lambda cnf: len(full_map.get(str(cnf).upper().strip(), [])) if full_map.get(str(cnf).upper().strip()) else obtener_numero_sectores_nominal(cnf)
        )

    if "TODOS" in str(fecha_sel):
        df_agrupado_hora = df_plot.groupby("Hora")["Sectores_Activos"].mean().reset_index()
        fig_timeline = px.line(
            df_agrupado_hora, x="Hora", y="Sectores_Activos",
            title=f"Curva Promedio de Apertura ({tipo_sector_sel}) - ACC: {acc_sel}", markers=True
        )
    else:
        fig_timeline = px.line(
            df_plot, x="Hora", y="Sectores_Activos", text="Configuracion",
            title=f"Curva de Apertura ({tipo_sector_sel}) - ACC: {acc_sel} ({fecha_sel})", markers=True
        )
        fig_timeline.update_traces(textposition="top center")

    fig_timeline.update_traces(line_color="#2b5c8f", line_width=3)
    st.plotly_chart(fig_timeline, use_container_width=True)

    st.markdown("---")
    st.markdown(f"### 📊 Estadísticas de Uso de Configuraciones y Sectores ({tipo_sector_sel})")

    total_minutos_global = df_plot["Duracion_Min"].sum()
    sec_min = int(df_plot["Sectores_Activos"].min()) if not df_plot.empty else 0
    sec_max = int(df_plot["Sectores_Activos"].max()) if not df_plot.empty else 0
    sec_mean = float(df_plot["Sectores_Activos"].mean()) if not df_plot.empty else 0.0

    stat_c1, stat_c2, stat_c3, stat_c4 = st.columns(4)
    with stat_c1:
        st.metric(label="📉 SECTORES MÍNIMOS", value=f"{sec_min}")
    with stat_c2:
        st.metric(label="📈 SECTORES MÁXIMOS", value=f"{sec_max}")
    with stat_c3:
        st.metric(label="📊 MEDIA EN SALA", value=f"{sec_mean:.2f} sec.")
    with stat_c4:
        st.metric(label="⏱️ TIEMPO TOTAL ANALIZADO", value=f"{total_minutos_global:,} min")

    st.markdown("")

    col_stat_table, col_stat_summary = st.columns([3, 2])

    with col_stat_table:
        st.markdown("#### 📑 Tabla de Frecuencia y Minutos por Configuración")
        df_freq_cfg = (
            df_plot.groupby("Configuracion")
            .agg(
                Ocurrencias=("Hora", "count"),
                Minutos_Totales=("Duracion_Min", "sum"),
                Sectores_Contados=("Sectores_Activos", "first")
            )
            .reset_index()
        )
        df_freq_cfg["Porcentaje Tiempo (%)"] = ((df_freq_cfg["Minutos_Totales"] / total_minutos_global) * 100).round(2)
        df_freq_cfg = df_freq_cfg.sort_values(by="Minutos_Totales", ascending=False)
        st.dataframe(df_freq_cfg, use_container_width=True, hide_index=True)

    with col_stat_summary:
        st.markdown("#### 💡 Conclusiones Operativas Automáticas")
        if not df_freq_cfg.empty:
            top_cfg = df_freq_cfg.iloc[0]["Configuracion"]
            top_min = df_freq_cfg.iloc[0]["Minutos_Totales"]
            top_pct = df_freq_cfg.iloc[0]["Porcentaje Tiempo (%)"]
            st.info(
                f"🔹 **Configuración Dominante:** La estructura **`{top_cfg}`** acumula mayor tiempo operativo, "
                f"con **{top_min} minutos** ({top_pct}% del total temporal).\n\n"
                f"🔹 **Carga de Sala:** Oscila entre **{sec_min} y {sec_max} sectores simultáneos**."
            )

    st.markdown("---")
    g1, g2 = st.columns(2)

    with g1:
        st.subheader("⏱️ Minutos Operativos por Turno y Configuración")
        fig_bar, ax_bar = plt.subplots(figsize=(8, 5))
        pivot_bar = df_plot.groupby(["Configuracion", "Turno"])["Duracion_Min"].sum().unstack(fill_value=0)
        pivot_bar.plot(kind="barh", stacked=True, ax=ax_bar, colormap="YlGnBu")
        ax_bar.set_xlabel("Minutos Acumulados")
        ax_bar.set_ylabel("Configuración")
        ax_bar.legend(title="Turno", loc="lower right", fontsize=9)
        st.pyplot(fig_bar)
        plt.close(fig_bar)

    with g2:
        st.subheader("🔥 Mapa de Calor: Minutos por Configuración y Turno")
        fig_heat, ax_heat = plt.subplots(figsize=(8, 5))
        pivot_data = df_plot.groupby(["Configuracion", "Turno"])["Duracion_Min"].sum().unstack(fill_value=0)
        sns.heatmap(pivot_data, annot=True, fmt="d", cmap="YlGnBu", ax=ax_heat, cbar=False)
        ax_heat.set_ylabel("Configuración")
        ax_heat.set_xlabel("Turno")
        st.pyplot(fig_heat)
        plt.close(fig_heat)


def dibujar_subtab_22_colapsados(df_base, full_map, acc_sel, fecha_sel, turno_sel):
    from plotly.subplots import make_subplots
    st.subheader("🚀 Dinámica Secuencial Cuantitativa de Desdobles y Colapsos")
    if "TODOS" in str(fecha_sel):
        df_dia_completo = df_base.sort_values(by=["Fecha", "Hora"])
    else:
        df_dia_completo = df_base.sort_values(by="Hora")

    secuencia_eventos = []
    for i in range(len(df_dia_completo)):
        fila_actual = df_dia_completo.iloc[i]
        cnf_actual = fila_actual["Configuracion"]
        hora_cambio = fila_actual["Hora"]
        turno_actual = fila_actual["Turno"]
        f_val = fila_actual["Fecha"]
        sectores_actuales = full_map.get(cnf_actual, set())
        
        if i == 0:
            secuencia_eventos.append({
                "Fecha": f_val, "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"Inicio ({cnf_actual})",
                "Acción": "Apertura Inicial", "Sectores Implicados": ", ".join(sorted(list(sectores_actuales))),
                "Delta_Sectores": 0, "Sectores Totales": len(sectores_actuales)
            })
        else:
            cnf_previa = df_dia_completo.iloc[i-1]["Configuracion"]
            sectores_previos = full_map.get(cnf_previa, set())
            delta = len(sectores_actuales) - len(sectores_previos)
            
            if delta > 0:
                abiertos = sectores_actuales - sectores_previos
                secuencia_eventos.append({
                    "Fecha": f_val, "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "🟢 DESDOBLAMIENTO (Expansión)", "Sectores Implicados": ", ".join(sorted(list(abiertos))),
                    "Delta_Sectores": delta, "Sectores Totales": len(sectores_actuales)
                })
            elif delta < 0:
                colapsados = sectores_previos - sectores_actuales
                secuencia_eventos.append({
                    "Fecha": f_val, "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "🔴 COLLAPSE (Integración)", "Sectores Implicados": ", ".join(sorted(list(colapsados))),
                    "Delta_Sectores": delta, "Sectores Totales": len(sectores_actuales)
                })
            else:
                secuencia_eventos.append({
                    "Fecha": f_val, "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "Estable", "Sectores Implicados": "Ninguno",
                    "Delta_Sectores": 0, "Sectores Totales": len(sectores_actuales)
                })

    df_secuencia = pd.DataFrame(secuencia_eventos)
    if turno_sel != "TODOS":
        df_secuencia = df_secuencia[df_secuencia["Turno"] == turno_sel]

    if not df_secuencia.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        df_barras = df_secuencia[df_secuencia["Acción"] != "Apertura Inicial"]
        df_desdobles = df_barras[df_barras["Delta_Sectores"] > 0]
        df_colapsos = df_barras[df_barras["Delta_Sectores"] < 0]
        
        if not df_desdobles.empty:
            fig.add_trace(go.Bar(x=df_desdobles["Hora"], y=df_desdobles["Delta_Sectores"], name="🟢 DESDOBLAMIENTO", marker_color="#2ca02c"), secondary_y=False)
        if not df_colapsos.empty:
            fig.add_trace(go.Bar(x=df_colapsos["Hora"], y=df_colapsos["Delta_Sectores"], name="🔴 COLLAPSE", marker_color="#d62728"), secondary_y=False)

        fig.add_trace(go.Scatter(x=df_secuencia["Hora"], y=df_secuencia["Sectores Totales"], name="📈 TOTAL SECTORES", mode="lines+markers", line=dict(color="#1f77b4", width=3, dash="dash")), secondary_y=True)
        fig.update_layout(title_text=f"Evolución de Tendencias - ACC: {acc_sel}", height=400)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_secuencia, use_container_width=True, hide_index=True)


def dibujar_subtab_23_gantt_sectores(df_base, full_map, fecha_sel, cs_hierarchy=None):
    st.subheader("🗺️ Perfil Geométrico de Apertura por Puestos (Gantt)")
    turno_sel = st.selectbox("Filtrar por Turno Operativo:", options=["Todos", "Mañana", "Tarde", "Noche"], key="gantt_turno")

    df_dia = df_base.copy()
    if turno_sel != "Todos" and "Turno" in df_dia.columns:
        df_dia = df_dia[df_dia["Turno"] == turno_sel]

    df_dia = df_dia.sort_values(by=["Fecha", "Hora"])
    if df_dia.empty:
        st.warning("No hay registros operativos.")
        return

    registros_gantt = []
    for idx, fila in df_dia.iterrows():
        cnf, h_ini = str(fila["Configuracion"]), fila["Hora"]
        h_fin = fila["Hora_Fin"] if "Hora_Fin" in df_dia.columns else "23:59"
        f_val = fila["Fecha"] if "Fecha" in df_dia.columns else "2026-06-11"
        
        sectores_activos = full_map.get(cnf, set())
        total_activos = len(sectores_activos) if sectores_activos else 1
        
        for sec in sectores_activos:
            tipo_sec = clasificar_sector(sec, cs_hierarchy)
            registros_gantt.append({
                "Sector": sec, "Inicio": f"{f_val} {h_ini}:00", "Fin": f"{f_val} {h_fin}:00",
                "Configuración Madre": cnf, "Carga_Sala": total_activos,
                "Tipo": "Sector Integrado (CS)" if tipo_sec == "CS" else "Sector Elemental (ES)"
            })

    df_gantt = pd.DataFrame(registros_gantt)
    if not df_gantt.empty:
        fig_gantt = px.timeline(df_gantt, x_start="Inicio", x_end="Fin", y="Sector", color="Carga_Sala", color_continuous_scale=px.colors.sequential.Cividis_r, title=f"Mapa de Densidad y Carga en Sala (Filtro: {turno_sel})")
        st.plotly_chart(fig_gantt, use_container_width=True)


def dibujar_subtab_24_predictivo(df_filtered, full_map, fecha_sel):
    st.subheader("🔮 Asistente Predictivo de Capacidad (Mapeo Histórico)")
    p_col1, p_col2 = st.columns(2)
    with p_col1:
        hora_test = st.text_input("⏱️ Hora a consultar (HH:MM):", value="13:30", key="pred_hora_input")
    
    prediccion = engine.predict_atc_behavior(df_filtered, full_map, hora_consulta=hora_test, fecha_referencia=str(fecha_sel))
    with p_col2:
        st.markdown(r"**🔮 Diagnóstico estadístico:**")
        p_item1, p_item2, p_item3 = st.columns(3)
        p_item1.metric(label="🟢 PROB. DESDOBLE", value=f"{prediccion['prob_desdoble']}%")
        p_item2.metric(label="🔴 PROB. FUSIÓN", value=f"{prediccion['prob_fusion']}%")
        p_item3.metric(label="⚪ PROB. ESTABLE", value=f"{prediccion['prob_estable']}%")


def render_tab3():
    st.header("3. Motor de Desdoblamiento Quirúrgico y Priorización $CS_i$")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** Motor de reconfiguración y auditoría geométrica para simular desdobles de sectores integrados ($CS$) en sub-bloques o elementos elementales ($ES / CS_i$).
        * **Datos requeridos:** Archivos `.SPC`, `.COS` y `.CFG` cargados previamente.
        * **Interacción del usuario:** Selección de ACC y sector $CS$ objetivo, consulta opcional del ranking histórico, edición manual o copia de la combinación deseada en el cajetín de parámetros y pulsación de **Ejecutar Desdoblamiento**. Los ficheros de salida se empaquetan en un `.zip` descargable y se almacenan automáticamente para exportación global.
        """)
        
    st.markdown("---")

    if not st.session_state.uploaded_spc:
        st.warning("⚠️ Carga los archivos .SPC en la Pestaña 1 para continuar.")
        return

    acc_map_raw, cs_hierarchy = engine.get_acc_cs_mapping(
        st.session_state.uploaded_spc,
        cfg_files=st.session_state.get("uploaded_cfg"),
        cos_files=st.session_state.get("uploaded_cos"),
    )

    if not acc_map_raw:
        st.error("No se detectaron sectores válidos en los archivos cargados.")
        return

    acc_map_por_prefijo = {}
    for acc_original, lista_cs in acc_map_raw.items():
        for cs in lista_cs:
            cs_clean = cs.strip().upper()
            if len(cs_clean) >= 4:
                prefijo_acc = cs_clean[:4]
                if prefijo_acc not in acc_map_por_prefijo:
                    acc_map_por_prefijo[prefijo_acc] = []
                if cs_clean not in acc_map_por_prefijo[prefijo_acc]:
                    acc_map_por_prefijo[prefijo_acc].append(cs_clean)

    acc_map = acc_map_por_prefijo if acc_map_por_prefijo else acc_map_raw

    sector_minutos_globales = {}
    full_map = engine.build_cfg_map(st.session_state.get("uploaded_cfg", [])) if st.session_state.get("uploaded_cfg") and hasattr(engine, "build_cfg_map") else {}
    if st.session_state.get("uploaded_cos") and full_map:
        for cos_file in st.session_state.uploaded_cos:
            try:
                content_bytes = cos_file.getvalue() if hasattr(cos_file, "getvalue") else cos_file
                for line in content_bytes.decode('latin-1', errors='ignore').splitlines():
                    p = line.split(";")
                    if len(p) >= 5:
                        h_ini, h_fin = p[2].strip(), p[3].strip()
                        dur = calcular_minutos_tramo(h_ini, h_fin)
                        cnf = p[4].strip().upper()
                        for s in full_map.get(cnf, set()):
                            sector_minutos_globales[s] = sector_minutos_globales.get(s, 0) + dur
            except Exception:
                pass

    col1, col2 = st.columns(2)
    with col1:
        lista_accs = sorted(list(acc_map.keys()))
        acc_sel = st.selectbox("1. Seleccionar ACC:", options=lista_accs, key="acc_select")
    with col2:
        opciones_cs = sorted(acc_map.get(acc_sel, []))
        cs_sel = st.selectbox("2. Sector Integrado (CS) a desdoblar:", options=opciones_cs, key=f"cs_select_{acc_sel}")

    if cs_sel:
        es_asociados = engine.get_es_for_cs(cs_sel, cs_hierarchy)
        st.markdown(f"### Análisis de Desdoblamiento para **{cs_sel}**")

        c_left, c_right = st.columns(2)

        with c_left:
            st.write("**🧩 Componentes Inferiores (ES y posibles $CS_i$ asociados con Minutos):**")
            if es_asociados:
                es_info_list = []
                for es in es_asociados:
                    mins = sector_minutos_globales.get(es, 0)
                    es_info_list.append(f"`{es}` ({mins:,} min)")
                st.info(" • " + "\n • ".join(es_info_list))
                
                sub_cs_candidatos = [k for k in cs_hierarchy.keys() if k != cs_sel and set(cs_hierarchy[k]).issubset(set(es_asociados))]
                if sub_cs_candidatos:
                    st.markdown("**🔄 Sub-bloques intermedios detectados ($CS_i$):**")
                    for sci in sub_cs_candidatos:
                        hijos_sci = cs_hierarchy[sci]
                        mins_sci = sector_minutos_globales.get(sci, 0)
                        st.code(f"{sci} [{mins_sci:,} min] ➔ {';'.join(hijos_sci)}", language="text")

                    st.markdown("---")
                    st.markdown("**🏆 Ranking de Combinaciones Operativas ($CS_i$):**")
                    
                    es_oficiales_set = set(es_asociados)
                    combinaciones_propuestas = []
                    
                    for sci in sub_cs_candidatos:
                        hijos_sci = set(cs_hierarchy[sci])
                        restantes = es_oficiales_set - hijos_sci
                        
                        if len(hijos_sci) + len(restantes) == len(es_oficiales_set):
                            mins_sci = sector_minutos_globales.get(sci, 0)
                            mins_restantes = sum(sector_minutos_globales.get(r, 0) for r in restantes)
                            mins_totales_combo = mins_sci + mins_restantes
                            
                            combo_str = f"{sci} + " + " + ".join(sorted(list(restantes)))
                            param_sugerido = f"{sci};" + ";".join(sorted(list(restantes)))
                            
                            combinaciones_propuestas.append({
                                "Combinación": combo_str,
                                "Minutos Operativos": mins_totales_combo,
                                "Copiar en Parámetros": param_sugerido
                            })
                    
                    if combinaciones_propuestas:
                        df_combos = pd.DataFrame(combinaciones_propuestas).sort_values(by="Minutos Operativos", ascending=False)
                        st.dataframe(df_combos, use_container_width=True, hide_index=True)
                        st.markdown("💡 *La combinación situada en la parte superior es la más frecuente en el histórico operativo.*")
                else:
                    st.markdown("💡 *Sugerencia:* Copia los sub-bloques preferidos en el campo de parámetros.")
            else:
                st.warning("No se encontraron elementos asociados a este CS.")

        with c_right:
            st.write("**⚙️ Parámetros de Simulación (Control Manual):**")
            target_es_input = st.text_input(
                "Sectores a desdoblar (separados por comas o ';'):",
                value=";".join(es_asociados) if es_asociados else "",
                key=f"target_es_input_{cs_sel}",
                help="Introduce la combinación de ES y/o CSi manteniendo la cobertura exacta."
            )
            btn_ejecutar = st.button("▶️ Ejecutar Desdoblamiento", type="primary", use_container_width=True)

        if btn_ejecutar:
            if not st.session_state.uploaded_cos:
                st.error("⚠️ Se requieren archivos .COS para ejecutar la auditoría.")
                st.stop()
            if not target_es_input.strip():
                st.warning("⚠️ Debes indicar al menos un sector en los parámetros.")
                st.stop()

            # =========================================================================
            # SALVAGUARDA DE INTEGRIDAD ESPACIAL
            # =========================================================================
            es_oficiales_set = set(engine.get_es_for_cs(cs_sel, cs_hierarchy))
            
            usuario_input_list = [s.strip().upper() for s in re.split(r'[,;]+', target_es_input) if s.strip()]
            usuario_input_set = set(usuario_input_list)

            usuario_es_expandidos = set()
            for item in usuario_input_set:
                if item in cs_hierarchy:
                    usuario_es_expandidos.update(cs_hierarchy[item])
                else:
                    usuario_es_expandidos.add(item)

            faltantes = es_oficiales_set - usuario_es_expandidos
            sobrantes = usuario_es_expandidos - es_oficiales_set

            if faltantes or sobrantes:
                st.error("🚨 **Error de Integridad Espacial:** La combinación introducida no respeta los límites del sector CS original.")
                if faltantes:
                    st.warning(f"⚠️ Faltan por cubrir los siguientes elementos de {cs_sel}: `{', '.join(sorted(faltantes))}`")
                if sobrantes:
                    st.warning(f"⚠️ Has incluido elementos ajenos: `{', '.join(sorted(sobrantes))}`")
                st.stop()
            else:
                st.success("🔒 **Validación superada:** La combinación cubre de forma exacta y disjunta el volumen del sector CS.")
            # =========================================================================

            with st.spinner("Ejecutando la simulación de sustitución de configuraciones..."):
                try:
                    (df_audit, df_cambios, fig_h, fig_m, zip_buf, log_verif) = engine.run_desdoble_audit(
                        spc_files=st.session_state.uploaded_spc,
                        cos_files=st.session_state.uploaded_cos,
                        cs_integrated=cs_sel,
                        target_es_str=target_es_input,
                        cfg_files=st.session_state.uploaded_cfg,
                    )
                    st.session_state.df_global = df_audit.copy()
                    
                    # Persistir en sesión para descarga global en Pestaña 5
                    st.session_state.last_zip_buffer = zip_buf
                    
                    st.success("✅ Simulación completada con éxito.")

                    zip_bytes = zip_buf.getvalue() if hasattr(zip_buf, "getvalue") else zip_buf
                    if zip_bytes and len(zip_bytes) > 0:
                        st.download_button(
                            label="📦 Descargar Archivos .COS Auditados (ZIP)", 
                            data=zip_bytes, 
                            file_name=f"audit_desdoble_{cs_sel}.zip", 
                            mime="application/zip",
                            key="btn_descarga_zip_auditoria"
                        )
                    else:
                        st.warning("⚠️ No se generaron archivos para descargar.")

                    if df_cambios is not None and not df_cambios.empty:
                        st.markdown("---")
                        st.subheader("📊 Auditoría Detallada y Matriz Pre-Post del Desdoble")
                        
                        kpi1, kpi2, kpi3 = st.columns(3)
                        kpi1.metric(label="🔄 TRAMOS AFECTADOS (CAMBIOS)", value=len(df_cambios))
                        kpi2.metric(label="✨ ÉXITOS NUEVOS", value=len(df_cambios[df_cambios["Resultado"] == "ÉXITO"]))
                        kpi3.metric(label="♻️ ÉXITOS (EXISTENTES)", value=len(df_cambios[df_cambios["Resultado"] == "ÉXITO (Existente)"]))
                        
                        st.markdown("#### 📑 Matriz de Transición de Configuraciones (PRE ➔ POST)")
                        if "CNF_PRE" in df_cambios.columns and "CNF_POST" in df_cambios.columns:
                            df_matriz = pd.crosstab(df_cambios["CNF_PRE"], df_cambios["CNF_POST"], margins=True)
                            st.dataframe(df_matriz, use_container_width=True)

                        st.markdown("#### 📋 Listado Tramo a Tramo para Auditoría")
                        st.dataframe(df_cambios, use_container_width=True, hide_index=True)
                    else:
                        st.info("ℹ️ La simulación finalizó, pero no se registraron cambios en los tramos de los archivos analizados.")

                except Exception as ex:
                    st.error(f"🚨 Error crítico durante la ejecución del motor de auditoría: {ex}")


def render_tab_inspeccion_espacio_aereo():
    st.header("4. Auditoría e Inspección Jerárquica: ACC ➔ Configuración ➔ CS ➔ ES")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** Visor de desglose espacial para auditar minutos de uso, mapas de calor por turno y distribución en árbol descendente desde el ACC hasta el sector elemental ($ES$).
        * **Datos requeridos:** Ficheros `.COS`, `.SPC` y `.CFG`.
        * **Interacción del usuario:** Selección del Centro ACC, ámbito temporal (ciclo completo o fecha específica) y nivel de jerarquía a consultar (Configuración, Sector Integrado o Sector Elemental).
        """)
        
    st.markdown("---")
    st.markdown("Consulta los **minutos totales de uso** y la **distribución por turno** a lo largo del ciclo o por fecha.")

    has_cos = bool(st.session_state.get("uploaded_cos"))
    has_spc = bool(st.session_state.get("uploaded_spc"))
    has_cfg = bool(st.session_state.get("uploaded_cfg"))

    if not has_cos:
        st.warning("⚠️ Carga al menos ficheros .COS en la Pestaña 1.")
        return

    all_dfs = []
    for cos_file in st.session_state.uploaded_cos:
        try:
            content_bytes = cos_file.getvalue() if hasattr(cos_file, "getvalue") else cos_file
            content_lines = content_bytes.decode('latin-1', errors='ignore').splitlines()
            rows = []
            for line in content_lines:
                p = line.split(";")
                if len(p) >= 5:
                    h_ini, h_fin = p[2].strip(), p[3].strip()
                    rows.append({
                        "Fecha": p[0].strip(),
                        "ACC": p[1].strip().upper(),
                        "Hora": h_ini,
                        "Hora_Fin": h_fin,
                        "Configuracion": p[4].strip().upper(),
                        "Duracion_Min": calcular_minutos_tramo(h_ini, h_fin),
                        "Turno": engine.get_shift(h_ini) if hasattr(engine, "get_shift") else "Mañana"
                    })
            df_parsed = pd.DataFrame(rows)
            if not df_parsed.empty:
                all_dfs.append(df_parsed)
        except Exception:
            pass

    df_hierarchy = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    if df_hierarchy.empty:
        st.error("No se pudieron extraer datos de los archivos .COS.")
        return

    full_map = engine.build_cfg_map(st.session_state.get("uploaded_cfg", [])) if has_cfg and hasattr(engine, "build_cfg_map") else {}
    
    cs_hierarchy = {}
    if has_spc and hasattr(engine, "get_acc_cs_mapping"):
        try:
            _, cs_hierarchy = engine.get_acc_cs_mapping(
                st.session_state.uploaded_spc,
                cfg_files=st.session_state.get("uploaded_cfg"),
                cos_files=st.session_state.get("uploaded_cos")
            )
        except Exception:
            pass

    st.markdown("---")
    st.markdown("### 🎛️ Selector de Ámbito Temporal y Jerarquía")
    
    h_col1, h_col2, h_col3 = st.columns(3)
    with h_col1:
        acc_list = sorted(list(df_hierarchy["ACC"].unique()))
        sel_acc = st.selectbox("1. Seleccionar ACC:", options=acc_list, key="hier_acc")
    
    fechas_acc = sorted(list(df_hierarchy[df_hierarchy["ACC"] == sel_acc]["Fecha"].unique()))
    with h_col2:
        sel_fecha = st.selectbox("2. Ámbito Temporal:", options=["TODOS LOS DÍAS (Ciclo Completo)"] + fechas_acc, key="hier_fecha")

    with h_col3:
        nivel_consulta = st.selectbox("3. Nivel de Consulta:", options=["Por Configuración", "Por Sector Integrado (CS)", "Por Sector Elemental (ES)"], key="hier_nivel")

    if sel_fecha == "TODOS LOS DÍAS (Ciclo Completo)":
        df_scope = df_hierarchy[df_hierarchy["ACC"] == sel_acc].copy()
    else:
        df_scope = df_hierarchy[(df_hierarchy["ACC"] == sel_acc) & (df_hierarchy["Fecha"] == sel_fecha)].copy()

    st.markdown("---")

    if nivel_consulta == "Por Configuración":
        st.markdown(f"#### 📊 Análisis de Tiempos y Frecuencia de Configuraciones en **{sel_acc}** ({sel_fecha})")
        if not df_scope.empty:
            agg_cfg = df_scope.groupby("Configuracion").agg(
                Ocurrencias=("Hora", "count"),
                Minutos_Totales=("Duracion_Min", "sum")
            ).reset_index()
            
            total_mins = agg_cfg["Minutos_Totales"].sum()
            agg_cfg["Porcentaje (%)"] = ((agg_cfg["Minutos_Totales"] / total_mins) * 100).round(2)
            agg_cfg = agg_cfg.sort_values(by="Minutos_Totales", ascending=False)
            
            col_t1, col_t2 = st.columns([2, 1])
            with col_t1:
                st.dataframe(agg_cfg, use_container_width=True, hide_index=True)
            with col_t2:
                fig_cfg = px.pie(agg_cfg, names="Configuracion", values="Minutos_Totales", title="Distribución por Minutos de Operación")
                st.plotly_chart(fig_cfg, use_container_width=True)

    elif nivel_consulta in ["Por Sector Integrado (CS)", "Por Sector Elemental (ES)"]:
        tipo_filtro = "CS" if "Integrado" in nivel_consulta else "ES"
        st.markdown(f"#### 🔥 Mapa de Calor y Tiempos de Sectores **{tipo_filtro}** por Turno en **{sel_acc}** ({sel_fecha})")
        
        if full_map and not df_scope.empty:
            registros_sector_turno = []
            sector_stats = {}
            
            for _, row in df_scope.iterrows():
                cnf = row["Configuracion"]
                dur = row["Duracion_Min"]
                turno = row["Turno"]
                sectors = full_map.get(cnf, set())
                
                for s in sectors:
                    if clasificar_sector(s, cs_hierarchy) == tipo_filtro:
                        registros_sector_turno.append({
                            "Sector": s,
                            "Turno": turno,
                            "Duracion_Min": dur,
                            "Configuracion": cnf
                        })
                        if s not in sector_stats:
                            sector_stats[s] = {"total_min": 0, "turnos": {"Mañana": 0, "Tarde": 0, "Noche": 0}, "cfgs": {}}
                        
                        sector_stats[s]["total_min"] += dur
                        sector_stats[s]["turnos"][turno] = sector_stats[s]["turnos"].get(turno, 0) + dur
                        sector_stats[s]["cfgs"][cnf] = sector_stats[s]["cfgs"].get(cnf, 0) + dur

            df_sec_flat = pd.DataFrame(registros_sector_turno)

            if not df_sec_flat.empty:
                fig_hm, ax_hm = plt.subplots(figsize=(10, max(5, len(sector_stats) * 0.3)))
                pivot_sec_turno = df_sec_flat.groupby(["Sector", "Turno"])["Duracion_Min"].sum().unstack(fill_value=0)
                
                for t in ["Mañana", "Tarde", "Noche"]:
                    if t not in pivot_sec_turno.columns:
                        pivot_sec_turno[t] = 0
                pivot_sec_turno = pivot_sec_turno[["Mañana", "Tarde", "Noche"]]

                sns.heatmap(pivot_sec_turno, annot=True, fmt="d", cmap="YlGnBu", ax=ax_hm, cbar=False)
                ax_hm.set_title(f"🔥 Tiempo de Apertura Acumulado en Minutos (Sectores {tipo_filtro})")
                ax_hm.set_ylabel(f"Sector ({tipo_filtro})")
                ax_hm.set_xlabel("Turno")
                
                st.pyplot(fig_hm)
                plt.close(fig_hm)

                st.markdown("---")
                lista_resumen = []
                for s, data in sector_stats.items():
                    lista_resumen.append({
                        f"Sector ({tipo_filtro})": s,
                        "Minutos Totales": data["total_min"],
                        "Mañana (min)": data["turnos"]["Mañana"],
                        "Tarde (min)": data["turnos"]["Tarde"],
                        "Noche (min)": data["turnos"]["Noche"]
                    })
                
                df_resumen = pd.DataFrame(lista_resumen).sort_values(by="Minutos Totales", ascending=False)
                st.markdown(f"#### 📋 Tabla Resumen de Tiempos (Sectores {tipo_filtro})")
                st.dataframe(df_resumen, use_container_width=True, hide_index=True)

                st.markdown("---")
                st.markdown(f"#### 🔄 Relación Detallada: Un Sector {tipo_filtro} ➔ Configuraciones y Turnos")
                sector_sel = st.selectbox(f"Selecciona un Sector {tipo_filtro} para ver sus configuraciones:", options=sorted(list(sector_stats.keys())), key=f"detail_{tipo_filtro}")
                
                if sector_sel:
                    data_sec = sector_stats[sector_sel]
                    tot_sec = data_sec["total_min"]
                    
                    st.write(f"⏱️ El sector **`{sector_sel}`** estuvo activo un total de **{tot_sec} minutos**.")
                    
                    c_det1, c_det2 = st.columns(2)
                    with c_det1:
                        st.markdown("**📅 Distribución por Turno:**")
                        df_turnos = pd.DataFrame(list(data_sec["turnos"].items()), columns=["Turno", "Minutos"])
                        df_turnos["Porcentaje (%)"] = ((df_turnos["Minutos"] / tot_sec) * 100).round(2)
                        st.dataframe(df_turnos, use_container_width=True, hide_index=True)
                        
                    with c_det2:
                        st.markdown("**⚙️ Presencia por Configuración:**")
                        df_cfgs = pd.DataFrame(list(data_sec["cfgs"].items()), columns=["Configuración", "Minutos"])
                        df_cfgs["Presencia (%)"] = ((df_cfgs["Minutos"] / tot_sec) * 100).round(2)
                        df_cfgs = df_cfgs.sort_values(by="Minutos", ascending=False)
                        st.dataframe(df_cfgs, use_container_width=True, hide_index=True)
            else:
                st.warning(f"No se encontraron Sectores {tipo_filtro} activos en este ámbito.")
        else:
            st.info("Se requiere cargar ficheros .CFG y .SPC válidos.")


def render_tab4():
    st.header("5. Exportación Global de Datasets y Simulación")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** Módulo unificado de salida para descargar datasets consolidados en formato Excel y los paquetes `.zip` generados por el motor de desdoblamiento quirúrgico.
        * **Datos requeridos:** Ficheros cargados e interacción previa en el motor de desdoblamiento (Pestaña 3).
        * **Interacción del usuario:** Descarga directa mediante botones optimizados para integración directa con herramientas de simulación como NEST.
        """)
        
    st.markdown("---")

    if not st.session_state.uploaded_cos:
        st.warning("⚠️ No hay datos cargados para exportar.")
        return

    dfs = [parse_cos_content(f.getvalue().decode('latin-1', errors='ignore')) for f in st.session_state.uploaded_cos]
    df_full = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    if not df_full.empty:
        st.subheader("📊 Dataset Consolidado General")
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
            df_full.to_excel(output_excel, index=False, sheet_name="Tramos")
        excel_data = output_excel.getvalue()
        st.download_button(
            label="📊 Descargar Dataset Consolidado en Excel (.xlsx)", 
            data=excel_data, 
            file_name="atfcm_export.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            use_container_width=True
        )

    st.markdown("---")
    st.subheader("📦 Paquete de Resultados del Motor de Desdoblamiento")
    if st.session_state.get("last_zip_buffer") is not None:
        zip_buf_stored = st.session_state.last_zip_buffer
        zip_bytes_stored = zip_buf_stored.getvalue() if hasattr(zip_buf_stored, "getvalue") else zip_buf_stored
        if zip_bytes_stored and len(zip_bytes_stored) > 0:
            st.success("✅ Se detectó un paquete de desdoblamiento listo para su descarga global.")
            st.download_button(
                label="📦 Descargar Archivos .COS Auditados y Configuraciones Virtuales (.ZIP)", 
                data=zip_bytes_stored, 
                file_name="audit_desdoble_global_export.zip", 
                mime="application/zip",
                use_container_width=True,
                key="btn_descarga_global_zip_export"
            )
        else:
            st.info("ℹ️ El buffer de desdoblamiento está vacío.")
    else:
        st.info("ℹ️ Ejecuta primero una simulación en la **Pestaña 3 (Motor de Desdoblamiento)** para generar y habilitar el paquete exportable de ficheros .COS y .CFG.")


def render_tab5():
    st.header("6. Metodología Operacional")
    
    with st.expander("📖 Guía de Uso e Información de la Pestaña", expanded=False):
        st.markdown("""
        * **Qué representa:** Marco teórico, definiciones normativas y especificaciones técnicas de los algoritmos de capacidad ATFCM.
        * **Datos requeridos:** Ninguno (Documentación de referencia).
        * **Interacción del usuario:** Consulta de documentación estática integrada.
        """)
        
    st.markdown("---")
    st.markdown(r"Módulo que documenta los principios técnicos y métricas ATFCM.")


def main():
    st.title("✈️ ATFCM Sector & Configuration Analyzer")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📁 Carga de Archivos",
        "📊 Análisis Global",
        "⚙️ Motor de Desdoblamiento",
        "🔍 Inspección Jerárquica",
        "💾 Exportación",
        "📖 Metodología"
    ])

    with tab1: render_tab1()
    with tab2: render_tab2()
    with tab3: render_tab3()
    with tab4: render_tab_inspeccion_espacio_aereo()
    with tab5: render_tab4()
    with tab6: render_tab5()


if __name__ == "__main__":
    main()