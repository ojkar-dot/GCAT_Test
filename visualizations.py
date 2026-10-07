import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_kpis_y_metricas(df_f):
    k1, k2, k3, k4 = st.columns(4)

    tot_horas = df_f["Duración (h)"].sum() if "Duración (h)" in df_f else 0.0
    tot_tramos = len(df_f)
    cfgs_unicas = (
        df_f["Configuración"].nunique() if "Configuración" in df_f else 0
    )
    accs_unicos = df_f["ACC"].nunique() if "ACC" in df_f else 0

    k1.metric("Horas Totales Operativas", f"{tot_horas:.2f} h")
    k2.metric("Total Tramos Analizados", f"{tot_tramos}")
    k3.metric("Configuraciones / CS Únicos", f"{cfgs_unicas}")
    k4.metric("ACCs Detectados", f"{accs_unicos}")


def asignar_turno(hora_str):
    """Clasifica la hora de inicio en turnos operativos estándar (ATC)."""
    try:
        h = int(str(hora_str).split(":")[0])
        if 7 <= h < 15:
            return "Mañana (07:00 - 15:00)"
        elif 15 <= h < 23:
            return "Tarde (15:00 - 23:00)"
        else:
            return "Noche (23:00 - 07:00)"
    except Exception:
        return "No Especificado"


def render_dashboard_despliegue(df_f):
    if df_f.empty:
        st.warning("No hay datos disponibles para mostrar el dashboard.")
        return

    # Copia del DataFrame para evitar SettingWithCopyWarning
    df_f = df_f.copy()

    # Añadir columna de turno operativo
    if "Hora Inicio" in df_f.columns:
        df_f["Turno"] = df_f["Hora Inicio"].apply(asignar_turno)
    else:
        df_f["Turno"] = "General"

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("⏱️ Configuraciones (CS) Más Usadas")
        if "Configuración" in df_f.columns:
            g_cfg = (
                df_f.groupby("Configuración")["Duración (h)"]
                .sum()
                .reset_index()
                .sort_values(by="Duración (h)", ascending=False)
                .head(15)
            )

            fig_cfg = px.bar(
                g_cfg,
                x="Duración (h)",
                y="Configuración",
                orientation="h",
                text_auto=".1f",
                color="Duración (h)",
                color_continuous_scale="Blues",
                title="Top 15 CS con Mayor Carga Horaria",
            )
            fig_cfg.update_layout(
                yaxis={"categoryorder": "total ascending"},
                height=380,
                margin=dict(l=10, r=10, t=40, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_cfg, use_container_width=True)

    with c2:
        st.subheader("📊 Distribución de CS por Turno / Carga")

        modo_vista = st.radio(
            "Ver desglose por:",
            ["Por Turno Operativo", "Por Fecha (Evolución)"],
            horizontal=True,
            key="radio_desglose_acc",
        )

        if modo_vista == "Por Turno Operativo":
            g_turno = (
                df_f.groupby(["Turno", "Configuración"])["Duración (h)"]
                .sum()
                .reset_index()
            )
            fig_turno = px.bar(
                g_turno,
                x="Turno",
                y="Duración (h)",
                color="Configuración",
                title="Horas por Configuración según Turno",
                labels={"Duración (h)": "Horas Acumuladas"},
            )
            fig_turno.update_layout(
                barmode="stack",
                height=350,
                margin=dict(l=10, r=10, t=40, b=10),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                ),
            )
            st.plotly_chart(fig_turno, use_container_width=True)

        else:
            g_fec_cfg = (
                df_f.groupby(["Fecha", "Configuración"])["Duración (h)"]
                .sum()
                .reset_index()
            )
            fig_fec_cfg = px.bar(
                g_fec_cfg,
                x="Fecha",
                y="Duración (h)",
                color="Configuración",
                title="Evolución Diaria de Configuraciones Usadas",
                labels={"Duración (h)": "Horas Acumuladas"},
            )
            fig_fec_cfg.update_layout(
                barmode="stack",
                height=350,
                margin=dict(l=10, r=10, t=40, b=10),
                xaxis_tickangle=-45,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                ),
            )
            st.plotly_chart(fig_fec_cfg, use_container_width=True)


def extraer_num_sectores(cfg_str):
    """Extrae el número de sectores del identificador de configuración (ej: CNF3C -> 3 sectores)."""
    match = re.search(r"\d+", str(cfg_str))
    if match:
        return f"{match.group(0)} Sectores"
    return str(cfg_str)


def generar_sankey_despliegue_dia(
    df, col_config="Configuración", col_hora="Hora Inicio"
):
    """Genera un diagrama Sankey que refleja el flujo de despliegue/agrupación de sectores."""
    st.subheader("🔀 Flujo de Despliegue de Sectores (Transiciones Diarias)")

    if df.empty or len(df) < 2:
        st.info(
            "Selecciona un día con al menos dos tramos para construir el flujo de despliegue."
        )
        return

    df_sorted = df.sort_values(by=col_hora).copy()

    df_sorted["N_Sectores"] = df_sorted[col_config].apply(
        lambda x: f"{x} ({extraer_num_sectores(x)})"
    )
    df_sorted["Siguiente_N_Sectores"] = df_sorted["N_Sectores"].shift(-1)

    df_transitions = df_sorted.dropna(subset=["Siguiente_N_Sectores"]).copy()

    if df_transitions.empty:
        st.info("No existen transiciones registradas para la fecha elegida.")
        return

    df_flow = (
        df_transitions.groupby(["N_Sectores", "Siguiente_N_Sectores"])
        .size()
        .reset_index(name="Transiciones")
    )

    nodos_origen = [f"{n} (Origen)" for n in df_flow["N_Sectores"]]
    nodos_destino = [f"{n} (Destino)" for n in df_flow["Siguiente_N_Sectores"]]

    todos_nodos = sorted(list(set(nodos_origen + nodos_destino)))
    mapa_indices = {nodo: idx for idx, nodo in enumerate(todos_nodos)}

    source_idx = [mapa_indices[n] for n in nodos_origen]
    target_idx = [mapa_indices[n] for n in nodos_destino]
    values = df_flow["Transiciones"].values

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=18,
                    thickness=15,
                    line=dict(color="#1A252C", width=0.5),
                    label=todos_nodos,
                    color="#2B5C8F",
                ),
                link=dict(
                    source=source_idx,
                    target=target_idx,
                    value=values,
                    color="rgba(160, 190, 220, 0.45)",
                ),
            )
        ]
    )

    fig.update_layout(
        font=dict(size=12),
        height=450,
        margin=dict(l=10, r=10, t=20, b=10),
    )

    st.plotly_chart(fig, use_container_width=True)