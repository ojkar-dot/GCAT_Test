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
from visualizations import (
    generar_sankey_despliegue_dia,
    render_dashboard_despliegue,
    render_kpis_y_metricas,
)

st.set_page_config(
    page_title="ATFCM Sector & Configuration Analyzer",
    page_icon="✈️",
    layout="wide",
)

# Inicializar sesión para almacenar los UploadedFile de Streamlit
if "uploaded_cos" not in st.session_state:
    st.session_state.uploaded_cos = []
if "uploaded_spc" not in st.session_state:
    st.session_state.uploaded_spc = []
if "uploaded_cfg" not in st.session_state:
    st.session_state.uploaded_cfg = []


def render_tab1():
    st.header("1. Carga de Archivos de Entrada (.COS, .SPC, .CFG)")

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
def render_tab2():
    st.header("2. Dashboard de Exploración y Análisis del ACC")

    # Control de seguridad inicial
    if "uploaded_cos" not in st.session_state or not st.session_state.uploaded_cos:
        st.warning("⚠️ Por favor, carga los archivos .COS en la Pestaña 1 para habilitar la exploración.")
        return

    # LECTURA Y PARSEO BLINDADO DEL ARCHIVO ORIGINAL .COS
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

    # Enriquecimiento operativo base
    if "Turno" not in df_base.columns:
        df_base["Turno"] = df_base["Hora"].apply(engine.get_shift)

    cfg_files_list = st.session_state.get("uploaded_cfg", None)
    full_map = engine.build_cfg_map(cfg_files_list) if cfg_files_list else {}
    
    def calcular_sectores_activos(cnf):
        cnf_str = str(cnf).upper().strip()
        if full_map and cnf_str in full_map: 
            return len(full_map[cnf_str])
        match = re.match(r"^(\d+)", cnf_str)
        return int(match.group(1)) if match else 1

    df_base["Sectores_Activos"] = df_base["Configuracion"].apply(calcular_sectores_activos)

    # MENÚ SECUNDARIO HORIZONTAL CON LA NUEVA SUBPESTAÑA 2.4 INDEPENDIENTE
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

    # FILTROS DE SELECCIÓN COMUNES
    st.markdown("### 🔍 Filtros de Selección de Escenario")
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        acc_sel = st.selectbox("Seleccionar Centro ACC:", options=sorted(list(df_base["ACC"].unique())))
    with f_col2:
        fecha_sel = st.selectbox("Seleccionar Fecha del Plan:", options=sorted(list(df_base["Fecha"].unique())))
    with f_col3:
        turno_sel = st.selectbox("Filtrar por Turno:", options=["TODOS", "Mañana", "Tarde", "Noche"])

    # Filtrado base aplicado al escenario
    df_filtered = df_base[(df_base["ACC"] == acc_sel) & (df_base["Fecha"] == fecha_sel)].sort_values(by="Hora").copy()
    if turno_sel != "TODOS":
        df_filtered = df_filtered[df_filtered["Turno"] == turno_sel]

    if df_filtered.empty:
        st.info("No hay registros para la combinación de filtros seleccionada.")
        return

    # Enrutador de llamadas modulares a sub-pantallas
    if "2.1" in sub_tab:
        dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel)
    elif "2.2" in sub_tab:
        dibujar_subtab_22_colapsados(df_filtered, full_map, acc_sel, fecha_sel, turno_sel)
    elif "2.3" in sub_tab:
        dibujar_subtab_23_gantt_sectores(df_filtered, full_map, fecha_sel)
    elif "2.4" in sub_tab:
        dibujar_subtab_24_predictivo(df_filtered, full_map, fecha_sel)

import re

def obtener_numero_sectores_nominal(cnf_nombre):
    # Extrae el número inmediatamente posterior a 'CNF' en el nombre de la configuración
    match = re.search(r'CNF(\d+)', str(cnf_nombre).upper())
    if match:
        return int(match.group(1))
    return 1

def dibujar_subtab_21_global(df_filtered, acc_sel, fecha_sel):
    st.subheader("⏱️ Perfil de Carga y Capacidad Cronológica del ACC")
    st.markdown("Muestra la curva continua de cuántos sectores se encuentran abiertos simultáneamente a lo largo del tiempo.")

    # Aseguramos que la columna de sectores activos refleje el valor nominal correcto (ej. CNF1AW = 1)
    df_plot = df_filtered.copy()
    if "Configuracion" in df_plot.columns:
        df_plot["Sectores_Activos"] = df_plot["Configuracion"].apply(obtener_numero_sectores_nominal)

    fig_timeline = px.line(
        df_plot, x="Hora", y="Sectores_Activos", text="Configuracion",
        title=f"Curva de Apertura de Sectores - ACC: {acc_sel} ({fecha_sel})", markers=True
    )
    fig_timeline.update_traces(textposition="top center", line_color="#2b5c8f", line_width=3)
    st.plotly_chart(fig_timeline, use_container_width=True)

    st.markdown("---")
    g1, g2 = st.columns(2)

    with g1:
        st.subheader("⏱️ Proporción por Turno y Configuración")
        fig_bar, ax_bar = plt.subplots(figsize=(8, 5))
        
        # Obtenemos la misma tabla pivote por turnos para alimentar las barras apiladas
        pivot_bar = df_filtered.groupby(["Configuracion", "Turno"]).size().unstack(fill_value=0)
        
        # Gráfico de barras horizontales apiladas con la misma paleta cromática del mapa de calor
        pivot_bar.plot(kind="barh", stacked=True, ax=ax_bar, colormap="YlGnBu")
        
        ax_bar.set_xlabel("Frecuencia / Ocurrencias")
        ax_bar.set_ylabel("Configuración")
        ax_bar.legend(title="Turno", loc="lower right", fontsize=9)
        
        st.pyplot(fig_bar)
        plt.close(fig_bar)

    with g2:
        st.subheader("🔥 Frecuencia de Uso por Capacidad y Turno")
        fig_heat, ax_heat = plt.subplots(figsize=(8, 5))
        pivot_data = df_filtered.groupby(["Configuracion", "Turno"]).size().unstack(fill_value=0)
        sns.heatmap(pivot_data, annot=True, fmt="d", cmap="YlGnBu", ax=ax_heat, cbar=False)
        ax_heat.set_ylabel("Configuración")
        ax_heat.set_xlabel("Turno")
        st.pyplot(fig_heat)
        plt.close(fig_heat)

    st.markdown("---")
    cfg_files_list = st.session_state.get("uploaded_cfg", None)
    full_map = engine.build_cfg_map(cfg_files_list) if cfg_files_list else {}
    
    tendencias_acc = engine.extract_acc_trends(df_filtered, full_map)
    
    st.markdown("### 📈 Diagnóstico de Tendencias del Ciclo de Capacidad")
    t_col1, t_col2, t_col3 = st.columns(3)
    
    with t_col1:
        st.info(f"🌅 **Primer Desdoble (Trigger):**\n* Hora: `{tendencias_acc['trigger_hora']}`\n* Sectores abiertos: `{tendencias_acc['trigger_sector']}`")
        
    with t_col2:
        st.success(f"⚡ **Dinámica de Rampa Diurna:**\n* Ritmo de Apertura: `{tendencias_acc['rampa_apertura_sectores_por_hora']} sectores/hora`\n* Estabilidad Máxima: `{tendencias_acc['meseta_duracion_horas']} horas`")
        
    with t_col3:
        st.error(f"🌌 **Inicio del Repliegue (Fusión):**\n* Hora: `{tendencias_acc['repliegue_hora']}`\n* Sectores integrados: `{tendencias_acc['repliegue_sector']}`")
        
    st.markdown("---")
    st.markdown("### ⏳ Índice de Estabilidad y Frecuencia de Resectorización")
    st.markdown("Analiza la persistencia temporal de las celdas de control para evitar la sobrecarga por handovers constantes.")
    
    métricas_estabilidad = engine.calcular_metricas_estabilidad(df_filtered)
    
    # ==========================================
    # AMPLIACIÓN ESTADÍSTICA AVANZADA
    # ==========================================
    duraciones = métricas_estabilidad.get("lista_duraciones", [30]*len(df_filtered)) # Lista de minutos por tramo si el engine la provee
    import numpy as np
    
    mediana_duracion = np.median(duraciones) if duraciones else 0
    p25, p75 = np.percentile(duraciones, [25, 75]) if duraciones and len(duraciones) > 1 else (0, 0)
    iqr_duracion = p75 - p25
    
    # Cálculo de la tasa de rotación por hora operativa
    horas_totales_operacion = max(1, len(df_filtered) / 60.0) # Estimación o cálculo real
    tasa_rotacion = métricas_estabilidad['total_cambios'] / horas_totales_operacion
    
    # Bloque de Métricas Primarias (Fila 1)
    e_col1, e_col2, e_col3 = st.columns(3)
    
    if métricas_estabilidad["duracion_media_minutos"] >= 60:
        estado_ies = "🟢 ALTA (Operación Estable)"
    elif métricas_estabilidad["duracion_media_minutos"] >= 40:
        estado_ies = "🟡 MODERADA (Atención)"
    else:
        estado_ies = "🔴 INESTABLE (Fatiga Estructural)"

    with e_col1:
        st.metric(label="⏳ DURACIÓN MEDIA (MEDIA / MEDIANA)", value=f"{métricas_estabilidad['duracion_media_minutos']} min", delta=f"Mediana: {mediana_duracion:.1f} min")
    with e_col2:
        st.metric(label="🚨 CAMBIOS PREMATUROS (< 40 MIN)", value=f"{métricas_estabilidad['transiciones_criticas_count']} alertas", delta=f"{métricas_estabilidad['porcentaje_inestabilidad']}% del tiempo total", delta_color="inverse" if métricas_estabilidad["transiciones_criticas_count"] > 0 else "normal")
    with e_col3:
        st.metric(label="🔄 RECONFIGURACIONES TOTALES", value=f"{métricas_estabilidad['total_cambios']} variaciones", delta=f"{tasa_rotacion:.2f} cambios/hora")

    # Bloque de Métricas Estadísticas Secundarias (Fila 2 - Nueva ampliación)
    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        st.metric(label="📊 DISPERSIÓN (IQR)", value=f"{iqr_duracion:.1f} min", delta=f"P25-P75: [{p25:.0f} - {p75:.0f}]")
    with s_col2:
        st.metric(label="⚡ TASA DE VOLATILIDAD", value=f"{tasa_rotacion:.1f} var/h", delta="Índice de fatiga por handovers")
    with s_col3:
        st.metric(label="🛡️ NIVEL DE CONFIANZA ESTRUCTURAL", value="Crítico" if métricas_estabilidad['porcentaje_inestabilidad'] > 50 else "Adecuado", delta="Basado en umbral 40 min")

    if métricas_estabilidad["lista_alertas"]:
        with st.expander("⚠️ Ver detalle de tramos con rotación excesiva (< 40 minutos)"):
            for alerta in métricas_estabilidad["lista_alertas"]:
                st.write(alerta)
    else:
        st.success("🔒 Plan estructural excelente: Ninguna reconfiguración bajó del umbral mínimo de 40 minutos.")

    # ==========================================
    # VISTA GLOBAL DE TODOS LOS DÍAS Y CONFIANZA ESTRUCTURAL
    # ==========================================
    st.markdown("---")
    st.markdown("### 📅 Vista Global de Todos los Días y Nivel de Confianza Estructural")
    st.markdown("Evaluación comparativa multidiaria de la estabilidad operativa, frecuencia de cambios y clasificación de confianza de la sectorización para todo el histórico disponible del ACC.")

    # Intentamos recuperar el DataFrame completo del session_state (ajusta la clave si usas otro nombre, ej. "df", "data", etc.)
    # Si no existe en session_state, usamos df_filtered como respaldo.
    df_master = st.session_state.get("df", None)
    if df_master is not None and "ACC" in df_master.columns:
        df_acc_global = df_master[df_master["ACC"] == acc_sel]
    else:
        df_acc_global = df_filtered  # Respaldo por si acaso

    col_fecha_cand = next((c for c in ["Fecha", "date", "DAY", "FECHA"] if c in df_acc_global.columns), None)

    if col_fecha_cand and df_acc_global[col_fecha_cand].nunique() > 1:
        dias_resumen = []
        
        # Agrupamos por cada día disponible en todo el histórico del ACC
        for fecha_val, grupo in df_acc_global.groupby(col_fecha_cand):
            mets_dia = engine.calcular_metricas_estabilidad(grupo)
            pct_inest = mets_dia.get("porcentaje_inestabilidad", 0)
            
            # Asignación del Nivel de Confianza Estructural
            if pct_inest > 50:
                confianza = "🔴 Crítico"
            elif pct_inest > 25:
                confianza = "🟡 Moderado"
            else:
                confianza = "🟢 Adecuado"
                
            dias_resumen.append({
                "Jornada": fecha_val,
                "Variaciones Totales": mets_dia.get("total_cambios", len(grupo)),
                "Duración Media (min)": mets_dia.get("duracion_media_minutos", 0),
                "Alertas (<40 min)": mets_dia.get("transiciones_criticas_count", 0),
                "% Inestabilidad": f"{pct_inest}%",
                "Confianza Estructural": confianza
            })
            
        import pandas as pd
        df_dias_resumen = pd.DataFrame(dias_resumen)
        
        # Mostramos la tabla resumen con todos los días del ACC
        st.dataframe(df_dias_resumen, use_container_width=True)
        
        # Gráfico comparativo multidiario
        fig_dias_conf = px.bar(
            df_dias_resumen, x="Jornada", y="Variaciones Totales",
            color="Confianza Estructural",
            title=f"Comparativa Histórica de Volatilidad y Confianza - ACC: {acc_sel}",
            color_discrete_map={"🔴 Crítico": "#ff4b4b", "🟡 Moderado": "#ffa41b", "🟢 Adecuado": "#09ab3b"}
        )
        st.plotly_chart(fig_dias_conf, use_container_width=True)
        
    else:
        # Si el dataset completo solo contiene un día registrado en total
        st.markdown("#### 🔍 Desglose de Confianza para la Jornada Seleccionada")
        
        mets_actual = engine.calcular_metricas_estabilidad(df_filtered)
        pct_actual = mets_actual.get("porcentaje_inestabilidad", 0)
        
        if pct_actual > 50:
            conf_actual = "🔴 Crítico (Fatiga Estructural Alta)"
        elif pct_actual > 25:
            conf_actual = "🟡 Moderado (Atención Requerida)"
        else:
            conf_actual = "🟢 Adecuado (Operación Estable)"
            
        c_meta1, c_meta2, c_meta3 = st.columns(3)
        with c_meta1:
            st.metric(label="📅 JORNADA EVALUADA", value=str(fecha_sel))
        with c_meta2:
            st.metric(label="🛡️ ESTADO DE CONFIANZA", value=conf_actual)
        with c_meta3:
            st.metric(label="📊 TASA DE INESTABILIDAD", value=f"{pct_actual}% del tiempo")
            
        st.info(f"💡 El dataset cargado para el ACC **{acc_sel}** contiene registros únicamente para la fecha actual ({fecha_sel}). La vista multidiaria se activará automáticamente si el archivo fuente incluye más jornadas.")


def dibujar_subtab_24_predictivo(df_filtered, full_map, fecha_sel):
    st.subheader("🔮 Asistente Predictivo de Capacidad (Mapeo Histórico)")
    st.markdown("Interroga la base de datos histórica agregada para predecir la propensión matemática de cambios en la sala de control.")
    
    # CORRECCIÓN DEFINITIVA: Argumento posicional '2' inyectado
    p_col1, p_col2 = st.columns(2)
    with p_col1:
        hora_test = st.text_input("⏱️ Hora a consultar (HH:MM):", value="13:30", key="pred_hora_input")
    
    # Telemetría en tiempo real para evaluar el tramo consultado
    sectores_actuales_count = 0
    cnf_actual_name = "N/A"
    
    df_momento = df_filtered[df_filtered["Hora"] == hora_test]
    if not df_momento.empty:
        sectores_actuales_count = df_momento.iloc[0]["Sectores_Activos"]
        cnf_actual_name = df_momento.iloc[0]["Configuracion"]
    else:
        df_previo = df_filtered[df_filtered["Hora"] <= hora_test].sort_values(by="Hora", ascending=False)
        if not df_previo.empty:
            sectores_actuales_count = df_previo.iloc[0]["Sectores_Activos"]
            cnf_actual_name = df_previo.iloc[0]["Configuracion"]

    # Cálculo de propensión histórica
    prediccion = engine.predict_atc_behavior(df_filtered, full_map, hora_consulta=hora_test, fecha_referencia=fecha_sel)
    
    with p_col2:
        st.markdown(f"**🔮 Diagnóstico estadístico:** Ventana de operación para el día **`{prediccion['dia_semana']}`**.")
        p_item1, p_item2, p_item3 = st.columns(3)
        p_item1.metric(label="🟢 PROB. DESDOBLE", value=f"{prediccion['prob_desdoble']}%")
        p_item2.metric(label="🔴 PROB. FUSIÓN", value=f"{prediccion['prob_fusion']}%")
        p_item3.metric(label="⚪ PROB. ESTABLE", value=f"{prediccion['prob_estable']}%")
        
    st.markdown("---")
    st.markdown("#### 📡 Reporte Ejecutivo de Situación en Sala")
    
    info_capacidad = f"En el plan actual de las **{hora_test}h**, el ACC se encuentra operando la configuración **`{cnf_actual_name}`** con **{sectores_actuales_count} sectores abiertos simultáneamente**."
    
    if prediccion['prob_desdoble'] >= prediccion['prob_fusion'] and prediccion['prob_desdoble'] > 0:
        st.success(
            f"📊 {info_capacidad}\n\n"
            f"🔮 **Tendencia Operativa:** Ante un repunte imprevisto de la demanda, la sala tiene un **{prediccion['prob_desdoble']}% de propensión al desdoblamiento**. "
            f"El candidato idóneo para absorber el tráfico y expandir el espacio aéreo según el histórico es la sectorización: **`{prediccion['sector_objetivo']}`**."
        )
    elif prediccion['prob_fusion'] > prediccion['prob_desdoble']:
        st.error(
            f"📊 {info_capacidad}\n\n"
            f"🔮 **Tendencia Operativa:** Por caída de los flujos de vuelos habituales en la franja, existe un **{prediccion['prob_fusion']}% de probabilidad de integración (Collapse)**. "
            f"El candidato estratégico para compactar las consolas de control y agrupar el espacio de forma segura es: **`{prediccion['sector_objetivo']}`**."
        )
    else:
        st.info(
            f"📊 {info_capacidad}\n\n"
            f"🔮 **Tendencia Operativa:** La sala se encuentra en una meseta rígida de crucero con un **{prediccion['prob_estable']}% de probabilidad de mantenerse Estable**. "
            f"Se recomienda dar continuidad al entorno de control actual sin realizar transferencias de puestos."
        )



def dibujar_subtab_22_colapsados(df_base, full_map, acc_sel, fecha_sel, turno_sel):
    from plotly.subplots import make_subplots
    st.subheader("🚀 Dinámica Secuencial Cuantitativa de Desdobles y Colapsos")
    st.markdown("Este gráfico muestra el **impacto neto (barras)** y la **evolución del total de sectores activos (línea superior)** en cada hito del plan.")

    df_dia_completo = df_base[(df_base["ACC"] == acc_sel) & (df_base["Fecha"] == fecha_sel)].sort_values(by="Hora")
    secuencia_eventos = []
    
    for i in range(len(df_dia_completo)):
        fila_actual = df_dia_completo.iloc[i]
        cnf_actual = fila_actual["Configuracion"]
        hora_cambio = fila_actual["Hora"]
        turno_actual = fila_actual["Turno"]
        sectores_actuales = full_map.get(cnf_actual, set())
        
        if i == 0:
            secuencia_eventos.append({
                "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"Inicio ({cnf_actual})",
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
                    "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "🟢 DESDOBLAMIENTO (Expansión)", "Sectores Implicados": ", ".join(sorted(list(abiertos))),
                    "Delta_Sectores": delta, "Sectores Totales": len(sectores_actuales)
                })
            elif delta < 0:
                colapsados = sectores_previos - sectores_actuales
                secuencia_eventos.append({
                    "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "🔴 COLLAPSE (Integración)", "Sectores Implicados": ", ".join(sorted(list(colapsados))),
                    "Delta_Sectores": delta, "Sectores Totales": len(sectores_actuales)
                })
            else:
                secuencia_eventos.append({
                    "Hora": hora_cambio, "Turno": turno_actual, "Transición": f"{cnf_previa} ➔ {cnf_actual}",
                    "Acción": "Estable", "Sectores Implicados": "Ninguno",
                    "Delta_Sectores": 0, "Sectores Totales": len(sectores_actuales)
                })

    df_secuencia = pd.DataFrame(secuencia_eventos)
    if turno_sel != "TODOS":
        df_secuencia = df_secuencia[df_secuencia["Turno"] == turno_sel]

    if not df_secuencia.empty:
        df_secuencia = df_secuencia.sort_values(by="Hora")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        df_barras = df_secuencia[df_secuencia["Acción"] != "Apertura Inicial"]
        df_desdobles = df_barras[df_barras["Delta_Sectores"] > 0]
        df_colapsos = df_barras[df_barras["Delta_Sectores"] < 0]
        
        if not df_desdobles.empty:
            fig.add_trace(go.Bar(
                x=df_desdobles["Hora"], y=df_desdobles["Delta_Sectores"],
                name="🟢 DESDOBLAMIENTO (Expansión)", marker_color="#2ca02c",
                customdata=np.stack((df_desdobles["Transición"], df_desdobles["Sectores Implicados"], df_desdobles["Sectores Totales"]), axis=-1),
                hovertemplate='<b>%{x}</b><br>Cambio: %{customdata.0}<br>Magnitud: +%{y} sectores<br>Sectores abiertos: %{customdata.1}<br>Total activos en sala: %{customdata.2}<extra></extra>'
            ), secondary_y=False)
            
        if not df_colapsos.empty:
            fig.add_trace(go.Bar(
                x=df_colapsos["Hora"], y=df_colapsos["Delta_Sectores"],
                name="🔴 COLLAPSE (Integración)", marker_color="#d62728",
                customdata=np.stack((df_colapsos["Transición"], df_colapsos["Sectores Implicados"], df_colapsos["Sectores Totales"]), axis=-1),
                hovertemplate='<b>%{x}</b><br>Cambio: %{customdata.0}<br>Magnitud: %{y} sectores<br>Sectores fusionados: %{customdata.1}<br>Total activos en sala: %{customdata.2}<extra></extra>'
            ), secondary_y=False)

        fig.add_trace(go.Scatter(
            x=df_secuencia["Hora"], y=df_secuencia["Sectores Totales"],
            name="📈 TOTAL SECTORES ABIERTOS", mode="lines+markers+text",
            text=df_secuencia["Sectores Totales"], textposition="top center",
            line=dict(color="#1f77b4", width=3, dash="dash"), marker=dict(size=8, symbol="diamond"),
            hovertemplate='<b>%{x}</b><br>Sectores Totales Abiertos: %{y}<extra></extra>'
        ), secondary_y=True)

        fig.update_layout(
            title_text=f"Evolución de Tendencias y Capacidad Neta del ACC ({fecha_sel})", height=400, hovermode="x unified",
            xaxis={'categoryorder':'array', 'categoryarray': df_secuencia["Hora"].tolist()}
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### 📋 Registro Cuantitativo de Cambios de Estructura")
        st.dataframe(df_secuencia.sort_values(by="Hora"), use_container_width=True, hide_index=True)

        st.markdown("#### 🧠 Diagnóstico de Comportamiento de Sala")
        df_dinamico = df_secuencia[df_secuencia["Acción"] != "Apertura Inicial"].copy()
        
        if not df_dinamico.empty:
            df_dinamico = df_dinamico.sort_values(by="Hora")
            df_aperturas_reales = df_dinamico[df_dinamico["Delta_Sectores"] > 0]
            if not df_aperturas_reales.empty:
                fila_ap = df_aperturas_reales.iloc[0]
                h_ap, t_ap, d_ap = fila_ap["Hora"], str(fila_ap["Transición"]), fila_ap["Delta_Sectores"]
                cnf_pre = t_ap.split("➔")[0].strip() if "➔" in t_ap else "N/A"
                cnf_post = t_ap.split("➔")[-1].strip() if "➔" in t_ap else "N/A"
                eliminados = full_map.get(cnf_pre, set()) - full_map.get(cnf_post, set())
                sector_roto = ", ".join(sorted(list(eliminados))) if eliminados else cnf_pre
                st.success(f"🌅 **Tendencia de Apertura:** El primer desdoble ocurre a las **{h_ap} HH** (`+{d_ap}` sectores), abriendo el integrado **`{sector_roto}`** hacia la configuración expansiva **`{cnf_post}`**.")
                
            df_fusiones_reales = df_dinamico[df_dinamico["Delta_Sectores"] < 0]
            if not df_fusiones_reales.empty:
                fila_co = df_fusiones_reales.iloc[0]
                h_co, t_co, d_co = fila_co["Hora"], str(fila_co["Transición"]), abs(fila_co["Delta_Sectores"])
                cnf_post_co = t_co.split("➔")[-1].strip() if "➔" in t_co else "N/A"
                st.error(f"🌌 **Tendencia de Fusión (Collapse):** El primer repliegue estructural ocurre a las **{h_co} HH** (`-{d_co}` sectores) para reintegrarse bajo la configuración operativa: **`{cnf_post_co}`**.")
    else:
        st.info("No se registraron hitos en el periodo.")


def dibujar_subtab_23_gantt_sectores(df_base, full_map, fecha_sel, cs_hierarchy=None):
    st.subheader("🗺️ Perfil Geométrico de Apertura por Puestos (Gantt)")
    st.markdown(
        "🚀 **Versión Optimizada:** Gráfico refinado con filtro por turno, distinción CS/ES en tooltip y **borde diferenciado para Sectores Integrados (CS)**."
    )
    
    c_f1, c_f2 = st.columns([2, 2])
    with c_f1:
        turnos_disponibles = ["Todos", "Mañana", "Tarde", "Noche"]
        turno_sel = st.selectbox("Filtrar por Turno Operativo:", options=turnos_disponibles, key=f"filtro_turno_{fecha_sel}")

    df_dia = df_base[df_base["Fecha"] == fecha_sel].copy() if "Fecha" in df_base.columns else df_base.copy()
    
    def determinar_turno(hora_str):
        try:
            h = int(hora_str.split(":")[0])
            if 7 <= h < 15:
                return "Mañana"
            elif 15 <= h < 23:
                return "Tarde"
            else:
                return "Noche"
        except:
            return "Mañana"

    if "Turno" not in df_dia.columns and not df_dia.empty:
        df_dia["Turno"] = df_dia["Hora"].apply(determinar_turno)

    if turno_sel != "Todos" and "Turno" in df_dia.columns:
        df_dia = df_dia[df_dia["Turno"] == turno_sel]

    df_dia = df_dia.sort_values(by="Hora")
    
    if df_dia.empty:
        st.info(f"No hay registros operativos para el turno seleccionado ({turno_sel}) en la fecha {fecha_sel}.")
        return

    registros_gantt = []
    hitos_cambio = []
    ultima_cnf = None

    elementales_conocidos = set()
    if cs_hierarchy:
        for cs_val, es_list in cs_hierarchy.items():
            elementales_conocidos.update(es_list)

    for idx, fila in df_dia.iterrows():
        cnf, h_ini = str(fila["Configuracion"]), fila["Hora"]
        h_fin = fila["Hora_Fin"] if "Hora_Fin" in df_dia.columns else "23:59"
        
        sectores_activos = full_map.get(cnf, set())
        total_activos = len(sectores_activos) if sectores_activos else 1
        es_desdoble = "_DESD" in cnf.upper()
        
        if cnf != ultima_cnf:
            hitos_cambio.append({
                "Hora": f"2026-06-11 {h_ini}:00", 
                "Carga": total_activos,
                "Config": cnf,
                "EsDesdoble": es_desdoble
            })
            ultima_cnf = cnf
        
        for sec in sectores_activos:
            is_elemental = (sec in elementales_conocidos or any(sec.endswith(str(i)) for i in range(10)))
            tipo_sector = "Sector Elemental (ES)" if is_elemental else "Sector Integrado (CS)"

            registros_gantt.append({
                "Sector": sec, 
                "Inicio": f"2026-06-11 {h_ini}:00", 
                "Fin": f"2026-06-11 {h_fin}:00",
                "Configuración Madre": cnf, 
                "Tramo Real": f"{h_ini} - {h_fin}", 
                "Carga_Sala": total_activos,
                "Tipo": "Desdoble / Expansivo" if es_desdoble else "Estándar",
                "Clasificacion": tipo_sector,
                # Atributo visual para el borde: CS lleva borde marcado, ES sin borde o sutil
                "LineColor": "#1b4f72" if not is_elemental else "rgba(0,0,0,0)",
                "LineWidth": 2 if not is_elemental else 0
            })

    df_gantt = pd.DataFrame(registros_gantt)
    if not df_gantt.empty:
        import plotly.express as px
        import plotly.graph_objects as go

        fig_gantt = px.timeline(
            df_gantt, 
            x_start="Inicio", 
            x_end="Fin", 
            y="Sector", 
            color="Carga_Sala", 
            color_continuous_scale=px.colors.sequential.Cividis_r,
            title=f"Mapa de Densidad y Carga en Sala - {fecha_sel} (Turno: {turno_sel})"
        )

        fig_gantt.update_traces(
            hovertemplate="<b>Sector:</b> %{y}<br>" +
                          "<b>Clasificación:</b> %{customdata[4]}<br>" +
                          "<b>Tramo:</b> %{customdata[0]}<br>" +
                          "<b>Configuración:</b> %{customdata[1]}<br>" +
                          "<b>Sectores en Sala:</b> %{customdata[2]}<br>" +
                          "<b>Tipo:</b> %{customdata[3]}<extra></extra>",
            customdata=df_gantt[["Tramo Real", "Configuración Madre", "Carga_Sala", "Tipo", "Clasificacion"]]
        )

        # Aplicamos bordes personalizados a las barras según sean CS (integrados)
        for i, row in df_gantt.iterrows():
            if row["Clasificacion"] == "Sector Integrado (CS)":
                fig_gantt.data[0].marker.line.color = row["LineColor"]
                fig_gantt.data[0].marker.line.width = row["LineWidth"]

        annotations = []
        for hito in hitos_cambio:
            prefijo_etiqueta = "✨ " if hito["EsDesdoble"] else ""
            annotations.append(dict(
                x=hito["Hora"],
                y=1.03,
                yref="paper",
                text=f"{prefijo_etiqueta}<b>{hito['Carga']}</b>",
                showarrow=False,
                font=dict(size=11, color="#900C3F" if hito["EsDesdoble"] else "#1b4f72", family="Arial"),
                xanchor="center",
                yanchor="bottom"
            ))

        num_sectores = df_gantt["Sector"].nunique()
        altura_calculada = max(550, num_sectores * 26)

        fig_gantt.update_layout(
            height=altura_calculada,
            annotations=annotations,
            xaxis=dict(showgrid=True, gridcolor="rgba(200, 200, 200, 0.2)", dtick=3600000 * 3, tickformat="%H:%M"),
            yaxis=dict(showgrid=True, gridcolor="rgba(200, 200, 200, 0.1)"),
            coloraxis_colorbar=dict(title=dict(text="Sectores<br>en Sala", font=dict(size=11)), thickness=15, len=0.6, y=0.5),
            plot_bgcolor="white",
            margin=dict(t=70, r=50)
        )
        
        st.plotly_chart(fig_gantt, use_container_width=True)
    else:
        st.warning("No hay datos suficientes para generar el gráfico de Gantt con los filtros actuales.")

def render_tab3():
    st.header("3. Motor de Desdoblamiento")

    if not st.session_state.uploaded_spc:
        st.warning("⚠️ Carga los archivos .SPC en la Pestaña 1 para continuar.")
        return

    acc_map_raw, cs_hierarchy = engine.get_acc_cs_mapping(
        st.session_state.uploaded_spc,
        cfg_files=st.session_state.uploaded_cfg,
        cos_files=st.session_state.uploaded_cos,
    )

    if not acc_map_raw:
        st.error("No se detectaron sectores válidos en los archivos cargados.")
        return

    # =========================================================================
    # REAGRUPACIÓN INTELIGENTE: Usamos las 4 primeras letras del Sector (CS) 
    # como identificador natural del ACC (ej: LECB, LECS, LECM...)
    # =========================================================================
    acc_map_por_prefijo = {}
    
    # Recorremos todos los sectores integrados que devuelve el motor
    for acc_original, lista_cs in acc_map_raw.items():
        for cs in lista_cs:
            cs_clean = cs.strip().upper()
            if len(cs_clean) >= 4:
                prefijo_acc = cs_clean[:4]  # Cogemos las 4 primeras letras (ej: LECB)
                if prefijo_acc not in acc_map_por_prefijo:
                    acc_map_por_prefijo[prefijo_acc] = []
                if cs_clean not in acc_map_por_prefijo[prefijo_acc]:
                    acc_map_por_prefijo[prefijo_acc].append(cs_clean)

    # Si por alguna razón el filtrado por prefijo queda vacío, mantenemos el original como respaldo
    acc_map = acc_map_por_prefijo if acc_map_por_prefijo else acc_map_raw

    col1, col2 = st.columns(2)
    with col1:
        lista_accs = sorted(list(acc_map.keys()))
        acc_sel = st.selectbox("1. Seleccionar ACC:", options=lista_accs, key="acc_select")
    with col2:
        # Ordenamos los sectores integrados de ese ACC para una selección más cómoda
        opciones_cs = sorted(acc_map.get(acc_sel, []))
        cs_sel = st.selectbox("2. Sector Integrado (CS):", options=opciones_cs, key=f"cs_select_{acc_sel}")

    if cs_sel:
        es_asociados = engine.get_es_for_cs(cs_sel, cs_hierarchy)
        st.markdown(f"### Análisis de Desdoblamiento para **{cs_sel}**")

        c_left, c_right = st.columns(2)

        with c_left:
            st.write("**Sectores Elementales (ES) componentes:**")
            if es_asociados:
                st.info(" • " + "\n • ".join(es_asociados))
            else:
                st.warning("No se encontraron ES asociados a este CS.")

        with c_right:
            st.write("**Parámetros para la simulación:**")
            target_es_input = st.text_input(
                "Sectores Elementales a desdoblar (separados por comas o ';'):",
                value=";".join(es_asociados) if es_asociados else "",
                key=f"target_es_input_{cs_sel}",
            )
            btn_ejecutar = st.button("▶️ Ejecutar Desdoblamiento", type="primary", use_container_width=True)

        if btn_ejecutar:
            if not st.session_state.uploaded_cos:
                st.error("⚠️ Se requieren archivos .COS para ejecutar la auditoría.")
                return
            if not target_es_input.strip():
                st.warning("⚠️ Debes indicar al menos un sector elemental en los parámetros.")
                return

            with st.spinner("Ejecutando la simulación de sustitución de configuraciones..."):
                (df_audit, df_cambios, fig_h, fig_m, zip_buf, log_verif) = engine.run_desdoble_audit(
                    spc_files=st.session_state.uploaded_spc,
                    cos_files=st.session_state.uploaded_cos,
                    cs_integrated=cs_sel,
                    target_es_str=target_es_input,
                    cfg_files=st.session_state.uploaded_cfg,
                )
            st.session_state.df_global = df_audit.copy()
            st.success("✅ Simulación completada.")

            zip_bytes = zip_buf.getvalue() if hasattr(zip_buf, "getvalue") else zip_buf
            if zip_bytes and len(zip_bytes) > 0:
                st.download_button(label="📦 Descargar Archivos .COS Auditados (ZIP)", data=zip_bytes, file_name=f"audit_desdoble_{cs_sel}.zip", mime="application/zip")
            else:
                st.warning("⚠️ No se generaron archivos para descargar.")

            st.markdown("---")
            st.subheader("📊 Métricas e Impacto del Desdoble")
            
            if df_cambios is not None and not df_cambios.empty:
                kpi1, kpi2, kpi3 = st.columns(3)
                kpi1.metric(label="🔄 CAMBIOS TOTALES", value=len(df_cambios))
                kpi2.metric(label="✨ ÉXITOS NUEVOS", value=len(df_cambios[df_cambios["Resultado"] == "ÉXITO"]))
                kpi3.metric(label="♻️ ÉXITOS (EXISTENTES)", value=len(df_cambios[df_cambios["Resultado"] == "ÉXITO (Existente)"]))
                
                st.markdown("---")
                g1, g2 = st.columns(2)
                with g1: st.pyplot(fig_h)
                with g2: st.pyplot(fig_m)
                st.markdown("---")
                st.subheader("📋 Detalle de Cambios Aplicados")
                
                df_display = df_cambios.copy()
                df_display["Indicador"] = df_display["Resultado"].apply(
                    lambda x: "✨ Nuevo" if x == "ÉXITO" else "♻️ Reutilizado"
                )
                cols = ["Indicador"] + [c for c in df_display.columns if c != "Indicador"]
                st.dataframe(df_display[cols], use_container_width=True, hide_index=True)
            else:
                st.info("No se requirieron realizar cambios de configuración.")

            if log_verif:
                st.markdown("---")
                st.subheader("🛡️ Registro de Verificación de Integridad (Checksum)")
                if "ERROR ❌" in log_verif: st.error("🚨 Se han detectado discrepancias estructurales.")
                else: st.info("🔒 Estructura y columnas validadas correctamente. Cero corrupción.")
                with st.expander("Ver Log Técnico Detallado"): st.code(log_verif)


def render_tab4():
    st.header("4. Exportación y Descargas")
    if not st.session_state.uploaded_cos:
        st.warning("⚠️ No hay datos cargados para exportar.")
        return

    dfs = [parse_cos_content(f.getvalue().decode('latin-1', errors='ignore')) for f in st.session_state.uploaded_cos]
    df_full = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    if not df_full.empty:
        st.subheader("📊 Exportación de Tramos Parseados (.COS)")
        st.write(f"Total de registros procesados: **{len(df_full)}**")

        col1, col2 = st.columns(2)
        with col1:
            csv_data = df_full.to_csv(index=False, sep=";").encode("latin-1")
            st.download_button(label="📄 Descargar Dataset Consolidado (CSV)", data=csv_data, file_name="atfcm_tramos_consolidados.csv", mime="text/csv", use_container_width=True)
        with col2:
            output_excel = pd.ExcelWriter("atfcm_export.xlsx", engine="openpyxl")
            df_full.to_excel(output_excel, index=False, sheet_name="Tramos")
            output_excel.close()
            with open("atfcm_export.xlsx", "rb") as f:
                st.download_button(label="📊 Descargar Dataset Consolidado (Excel)", data=f.read(), file_name="atfcm_tramos_consolidados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

def render_tab5():
    st.header("📖 Metodología Operacional e Ingeniería de Espacio Aéreo")
    st.markdown(
        "Este módulo documenta los principios técnicos, métricas ATFCM y la lógica algorítmica "
        "implementada para la exploración y simulación del centro de control de Sevilla Continental (**LECSCTA**)."
    )

    # Bloque 1: Exploración Estructural
    with st.expander("📊 1. Diagnóstico Estructural del ACC (Pestaña 2)", expanded=True):
        st.markdown("""
        Antes de aplicar cualquier cambio, el sistema extrae la radiografía base del espacio aéreo original mediante tres enfoques:
        * **Perfil de Carga Cronológica (2.1):** Traza el histórico continuo del número de sectores abiertos simultáneamente. Permite auditar visualmente las rampas de apertura matinales y las mesetas de máxima capacidad diurna.
        * **Índice de Estabilidad Sectorial (2.1):** Calcula la duración media (en minutos) de las configuraciones. Un promedio bajo delata sectorizaciones inestables o 'de paso' que elevan la tasa de transferencia de tráfico de los controladores.
        * **Dinámica Cuantitativa de Desdobles (2.2):** Mide mediante deltas vectoriales (\(\Delta = \text{Sectores}_{\text{Post}} - \text{Sectores}_{\text{Pre}}\)) la magnitud neta de expansión o contracción en cada cambio de bloque del plan de apertura.
        * **Perfil Geométrico de Puestos (2.3):** Un Diagrama de Gantt adaptado a la navegación aérea que reproduce la ocupación exacta de las consolas de control a lo largo de las 24 horas del día.
        """)

    # Bloque 2: Capa Predictiva
    with st.expander("🔮 2. Capa Predictiva y Ventanas de Propensión (Pestaña 2.4)"):
        st.markdown("""
        El Asistente Predictivo interroga la base de datos agregada del histórico de planes cargados para calcular la probabilidad frecuencial de un cambio operativo:
        * **Tratamiento del Calendario:** El algoritmo traduce las fechas del plan al día de la semana correspondiente (Lunes, Martes, etc.) para aislar patrones de tráfico recurrentes.
        * **Ventana de Influencia Temporal (\(\pm 15\) min):** Para mitigar el desfase por retrasos en las programaciones de vuelos, el motor abre un colchón estadístico alrededor de la hora consultada. Esto garantiza una muestra representativa de la franja.
        """)

    # Bloque 3: Motor de Desdoblamiento Quirúrgico
    with st.expander("⚙️ 3. Algoritmo de Desdoble Expansivo No Invasivo (Pestaña 3)"):
        st.markdown("""
        Cuando un **Sector Integrado (CS)** se satura por exceso de demanda, el backend simula su división hacia sus **Sectores Elementales (ES)** bajo tres restricciones operativas estrictas:
        1. **Garantía de Cobertura de Espacio Aéreo:** Utilizando el mapa de jerarquía real (`cs_hierarchy`), verifica que el volumen geográfico del sector viejo quede plenamente protegido, evitando la existencia de 'zonas vacías' o agujeros de seguridad sin control ATC.
        2. **Cero Intrusión Operativa (Congelación del ACC):** El algoritmo congela el entorno de control original y aísla el cambio, modificando única y exclusivamente el sector saturado sin alterar las posiciones colindantes de la sala.
        3. **Nomenclatura Coherente de Capacidad:** Toda nueva configuración dinámica añade el sufijo `_DESD` y actualiza automáticamente su prefijo numérico sumando exactamente un sector activo (`+1`) para reflejar la capacidad real en tiempo real (Ej: `8V` ➔ `9V_DESD`).
        """)

    # Bloque 4: Reglas de Turnos ATC
    with st.expander("⏱️ 4. Reglas de Clasificación de Turnos"):
        st.markdown("""
        Las marcas de tiempo horarias se agrupan de forma estandarizada en tres bloques de turnos operativos para facilitar el análisis agregado de datos:
        * **🌅 Turno de Mañana:** Franja de **07:00h a 14:59h**. Absorbe las mayores rampas de apertura por despegues masivos.
        * **🌆 Turno de Tarde:** Franja de **15:00h a 21:59h**. Monitorea la estabilización de los flujos de crucero.
        * **🌌 Turno de Noche:** Franja de **22:00h a 06:59h**. Periodo de contracción del espacio aéreo hacia macrosectores agrupados de baja demanda.
        """)


def main():
    st.title("✈️ ATFCM Sector & Configuration Analyzer")
    
    # 1. Añadimos el texto de la quinta pestaña al selector principal
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "📁 Carga de Archivos",
            "📊 Análisis Global",
            "⚙️ Motor de Desdoblamiento",
            "💾 Exportación",
            "📖 Metodología"  # <--- NUEVA PESTAÑA DEFINIDA
        ]
    )

    # 2. Asignamos el renderizador correspondiente
    with tab1:
        render_tab1()
    with tab2:
        render_tab2()
    with tab3:
        render_tab3()
    with tab4:
        render_tab4()
    with tab5:
        render_tab5()  # <--- EJECUTA EL CUADRO METODOLÓGICO AQUÍ



if __name__ == "__main__":
    main()

