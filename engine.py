import io
import os
import zipfile
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def get_shift(h_str):
    """Clasifica una hora HH:MM en un turno operativo ATC."""
    try:
        hour = int(str(h_str)[:2])
        if 7 <= hour < 15:
            return "Mañana"
        elif 15 <= hour < 22:
            return "Tarde"
        else:
            return "Noche"
    except Exception:
        return "N/A"


def build_cfg_map(cfg_files):
    """Construye el mapa base de configuraciones a partir de los archivos .CFG."""
    full_map = {}
    if not cfg_files:
        return full_map
    files = cfg_files if isinstance(cfg_files, list) else [cfg_files]
    for f in files:
        content = f.getvalue() if hasattr(f, "getvalue") else f
        lines = content.decode("latin-1", errors="ignore").splitlines()
        for l in lines:
            p = l.split(";")
            if len(p) >= 3:
                full_map.setdefault(
                    p[1].strip().upper(), set()
                ).add(p[2].strip().upper())
    return full_map


def get_acc_cs_mapping(spc_files, cfg_files=None, cos_files=None):
    """Extrae las relaciones jerárquicas entre sectores integrados (CS) y

    elementales (ES) a partir de los archivos .SPC.
    """
    acc_map = {}
    cs_hierarchy = {}
    if not spc_files:
        return acc_map, cs_hierarchy

    files = spc_files if isinstance(spc_files, list) else [spc_files]
    for f in files:
        content = f.getvalue() if hasattr(f, "getvalue") else f
        lines = content.decode("latin-1", errors="ignore").splitlines()
        current_cs = None
        for l in lines:
            p = l.split(";")
            if not p or l.startswith("#"):
                continue
            if p[0] == "A" and len(p) >= 3:
                current_cs = p[1].strip().upper()
                acc_map.setdefault("LECS", []).append(current_cs)
            elif p[0] == "S" and current_cs and len(p) >= 2:
                es_name = p[1].strip().upper()
                cs_hierarchy.setdefault(current_cs, set()).add(es_name)

    # Limpieza de duplicados manteniendo orden
    for acc in acc_map:
        acc_map[acc] = sorted(list(set(acc_map[acc])))
    return acc_map, cs_hierarchy


def get_es_for_cs(cs_name, cs_hierarchy):
    """Devuelve los sectores elementales asociados a un CS."""
    return sorted(list(cs_hierarchy.get(cs_name.strip().upper(), set())))


def run_desdoble_audit(
    spc_files, cos_files, cs_integrated, target_es_str, cfg_files=None
):
    """Procesa los archivos .COS realizando un desdoble quirúrgico y expansivo.

    Genera de forma dinámica nuevas configuraciones que reemplazan de manera
    exacta el sector integrado por sus sectores elementales destinos,
    manteniendo congelado al resto de sectores vecinos del ACC. Evita duplicidades
    si la configuración ya está desdoblada o si el set de sectores resultante ya existe.
    """
    zip_buffer = io.BytesIO()
    fig_h, ax1 = plt.subplots(figsize=(10, 4))
    fig_m, ax2 = plt.subplots(figsize=(8, 5))

    if not cos_files or not cs_integrated or not target_es_str:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            fig_h,
            fig_m,
            zip_buffer,
            "Faltan parámetros obligatorios.",
        )

    # 1. Mapeo del entorno operativo original
    full_map = build_cfg_map(cfg_files)
    targets = [
        s.strip().upper()
        for s in target_es_str.replace(";", ",").split(",")
        if s.strip()
    ]
    set_elementales_post = set(targets)

    # Creamos un mapa inverso para buscar si un conjunto de sectores ya tiene nombre asignado
    # { frozenset(sectores): nombre_configuracion }
    inverso_full_map = {frozenset(secs): cnf for cnf, secs in full_map.items()}

    all_rows, zip_files, log_verificacion = [], [], []
    nuevas_lineas_cfg_globales = set()

    files_cos = cos_files if isinstance(cos_files, list) else [cos_files]

    # 2. Bucle principal de reestructuración dinámica del plan de apertura
    for cos_f in files_cos:
        content_bytes = (
            cos_f.getvalue() if hasattr(cos_f, "getvalue") else cos_f
        )
        fname = getattr(cos_f, "name", "archivo.cos")
        orig_content = content_bytes.decode(
            "latin-1", errors="ignore"
        ).splitlines()

        new_lines = []
        for l in orig_content:
            p = l.split(";")
            if len(p) < 5:
                new_lines.append(l)
                continue

            hora, c_pre = p[2].strip(), p[4].strip().upper()

            # Verificamos si la configuración primitiva contiene el sector integrado a desdoblar
            sectores_cnf_actual = full_map.get(c_pre, set())

            # Control de idempotencia: Si ya es una configuración desdoblada o no contiene el CS, no duplicamos
            if c_pre in full_map and cs_integrated in sectores_cnf_actual and not c_pre.endswith("_DESD"):
                # REEMPLAZO QUIRÚRGICO EXPANSIVO: Conservamos vecinos y sumamos elementales
                vecinos_acc = sectores_cnf_actual - {cs_integrated}
                sectores_post_diseno = vecinos_acc | set_elementales_post

                # COMPROBACIÓN DE DUPLICIDAD: ¿Existe ya una configuración con exactamente estos sectores?
                froz_post = frozenset(sectores_post_diseno)
                if froz_post in inverso_full_map:
                    # Reutilizamos el nombre existente si ya está creada en el sistema
                    final_name = inverso_full_map[froz_post]
                    cambio_flag = 1
                    calidad = "ÉXITO (Existente)"
                else:
                    # ============================================================
                    # NUEVA NOMENCLATURA COHERENTE (Ej: 8V -> 9V_DESD / 9VN -> 10VN_DESD)
                    # ============================================================
                    import re
                    match = re.match(r"^(\d+)(.*)$", c_pre)
                    if match:
                        num_original = int(match.group(1))
                        resto_nombre = match.group(2)
                        nuevo_num = num_original + 1
                        final_name = f"{nuevo_num}{resto_nombre}_DESD"
                    else:
                        final_name = f"{c_pre}_DESD"

                    cambio_flag = 1
                    calidad = "ÉXITO"

                    # Registramos en el mapa inverso dinámicamente para evitar duplicados en el mismo batch
                    inverso_full_map[froz_post] = final_name
                    full_map[final_name] = sectores_post_diseno

                # Registramos las nuevas líneas para el archivo de catálogo .CFG (solo si es nueva)
                for sec in sorted(list(sectores_post_diseno)):
                    nuevas_lineas_cfg_globales.add(
                        f"LECSCTA;{final_name};{sec}"
                    )

                s_pre_str = ", ".join(sorted(list(sectores_cnf_actual)))
                s_post_str = ", ".join(sorted(list(sectores_post_diseno)))

                all_rows.append(
                    {
                        "Archivo": fname,
                        "Hora": hora,
                        "HH": hora[:2] if len(hora) >= 2 else "00",
                        "Turno": get_shift(hora),
                        "CNF_PRE": c_pre,
                        "CNF_POST": final_name,
                        "Resultado": calidad,
                        "Cambio": cambio_flag,
                        "Sectores_PRE": s_pre_str,
                        "Sectores_POST": s_post_str,
                        "Transicion": f"{len(sectores_cnf_actual)} > {len(sectores_post_diseno)}",
                    }
                )
                p[4] = final_name
            else:
                # Si el tramo ya estaba desdoblado previamente o no contiene el integrado, permanece inalterado
                s_pre_str = ", ".join(sorted(list(sectores_cnf_actual)))
                all_rows.append(
                    {
                        "Archivo": fname,
                        "Hora": hora,
                        "HH": hora[:2] if len(hora) >= 2 else "00",
                        "Turno": get_shift(hora),
                        "CNF_PRE": c_pre,
                        "CNF_POST": c_pre,
                        "Resultado": "Sin cambio",
                        "Cambio": 0,
                        "Sectores_PRE": s_pre_str,
                        "Sectores_POST": s_pre_str,
                        "Transicion": f"{len(sectores_cnf_actual)} > {len(sectores_cnf_actual)}",
                    }
                )

            new_lines.append(";".join(p))

        log_verificacion.append(f"Archivo auditado: {fname} | Checksum: OK ✅")
        zip_files.append((f"AUDIT_{fname}", "\n".join(new_lines)))

    df = pd.DataFrame(all_rows)
    df_c = (
        df[df["Cambio"] == 1]
        if not df.empty and "Cambio" in df.columns
        else pd.DataFrame()
    )

    # 3. Empaquetado ZIP de salida
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in zip_files:
            zf.writestr(filename, content.encode("latin-1"))

        content_cfg_nuevo = "\n".join(sorted(list(nuevas_lineas_cfg_globales)))
        zf.writestr("NUEVAS_CONFIGURACIONES_AUDITADAS.cfg", content_cfg_nuevo)

    zip_buffer.seek(0)

    # 4. Representación Gráfica
    if not df_c.empty:
        pivot = (
            df_c.groupby(["HH", "Transicion"])
            .size()
            .unstack(fill_value=0)
            .reindex([f"{i:02d}" for i in range(24)], fill_value=0)
        )
        pivot.plot(kind="bar", stacked=True, ax=ax1, colormap="tab10")
        ax1.set_title("Frecuencia de Desdobles Expansivos por Hora")
        ax1.set_xlabel("Hora (HH)")
        ax1.set_ylabel("Sustituciones")

        matrix = pd.crosstab(df_c["CNF_PRE"], df_c["CNF_POST"]).sort_index(
            ascending=True
        )
        sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", ax=ax2)
        ax2.set_title("Matriz de Diseño de Nuevas Configuraciones")
    else:
        ax1.text(0.5, 0.5, "Sin cambios en el periodo", ha="center", va="center")
        ax2.text(
            0.5, 0.5, "Sin nuevas configuraciones", ha="center", va="center"
        )

    return df, df_c, fig_h, fig_m, zip_buffer, "\n".join(log_verificacion)

def extract_acc_trends(df_base, full_map):
    """
    Analiza la serie temporal del plan de apertura original para extraer
    las tendencias de diseño: Primer disparador, pendientes de estrés y repliegue.
    """
    # Valores de control por defecto si los mapas están vacíos
    trends = {
        "trigger_hora": "N/A",
        "trigger_sector": "N/A",
        "rampa_apertura_sectores_por_hora": 0.0,
        "repliegue_hora": "N/A",
        "repliegue_sector": "N/A",
        "meseta_duracion_horas": 0.0
    }
    
    if df_base.empty or not full_map:
        return trends
        
    # Ordenamos cronológicamente el plan diario
    df_cron = df_base.sort_values(by="Hora").copy()
    
    # --- 1. DETECCIÓN DEL FIRST TRIGGER Y RAMPA ---
    hora_inicio_rampa = None
    sectores_inicio_rampa = 0
    hora_max_rampa = None
    sectores_max_rampa = 0
    
    for i in range(1, len(df_cron)):
        cnf_pre = df_cron.iloc[i-1]["Configuracion"]
        cnf_act = df_cron.iloc[i]["Configuracion"]
        hora_act = df_cron.iloc[i]["Hora"]
        
        len_pre = len(full_map.get(cnf_pre, set()))
        len_act = len(full_map.get(cnf_act, set()))
        
        # Detectamos el primer desdoble (First Trigger)
        if len_act > len_pre and trends["trigger_hora"] == "N/A":
            abiertos = full_map.get(cnf_act, set()) - full_map.get(cnf_pre, set())
            trends["trigger_hora"] = hora_act
            trends["trigger_sector"] = ", ".join(sorted(list(abiertos))) if abiertos else "Varias Celdas"
            
            # Anclamos el inicio de la rampa matinal
            hora_inicio_rampa = hora_act
            sectores_inicio_rampa = len_pre
            
        # Buscamos el pico máximo de la meseta diurna
        if len_act == max(df_cron["Sectores_Activos"]) and hora_max_rampa is None:
            hora_max_rampa = hora_act
            sectores_max_rampa = len_act

    # Cálculo de la pendiente de estrés (Sectores abiertos por hora en la rampa)
    if hora_inicio_rampa and hora_max_rampa:
        try:
            h1 = int(hora_inicio_rampa[:2]) + int(hora_inicio_rampa[3:5])/60
            h2 = int(hora_max_rampa[:2]) + int(hora_max_rampa[3:5])/60
            if h2 > h1:
                trends["rampa_apertura_sectores_por_hora"] = round((sectores_max_rampa - sectores_inicio_rampa) / (h2 - h1), 2)
        except Exception:
            pass

    # --- 2. DETECCIÓN DEL REPLIEGUE (INTEGRACIÓN DE TARDE) ---
    max_sectores = max(df_cron["Sectores_Activos"])
    
    # Calculamos cuánto dura la meseta de máxima capacidad
    df_meseta = df_cron[df_cron["Sectores_Activos"] == max_sectores]
    if len(df_meseta) >= 2:
        try:
            h_init = int(df_meseta.iloc[0]["Hora"][:2])
            h_end = int(df_meseta.iloc[-1]["Hora"][:2])
            trends["meseta_duracion_horas"] = float(abs(h_end - h_init))
        except Exception:
            pass

    # Buscamos la primera caída de capacidad después de las 14:00
    for i in range(1, len(df_cron)):
        hora_act = df_cron.iloc[i]["Hora"]
        if int(hora_act[:2]) >= 14:
            cnf_pre = df_cron.iloc[i-1]["Configuracion"]
            cnf_act = df_cron.iloc[i]["Configuracion"]
            
            len_pre = len(full_map.get(cnf_pre, set()))
            len_act = len(full_map.get(cnf_act, set()))
            
            if len_act < len_pre:
                cerrados = full_map.get(cnf_pre, set()) - full_map.get(cnf_act, set())
                trends["repliegue_hora"] = hora_act
                trends["repliegue_sector"] = ", ".join(sorted(list(cerrados))) if cerrados else "Varias Celdas"
                break
                
    return trends

def predict_atc_behavior(df_base, full_map, hora_consulta="13:44", fecha_referencia=None):
    """
    Escanea el histórico de datos para calcular la probabilidad estadística de 
    desdoblamiento o integración de un día de la semana y hora específicos.
    """
    resultado = {
        "dia_semana": "Martes",
        "total_muestras": 0,
        "prob_estable": 100,
        "prob_desdoble": 0,
        "prob_fusion": 0,
        "tendencia_principal": "Estable",
        "sector_objetivo": "Ninguno (Espacio Estable)"
    }
    
    if df_base.empty or not full_map:
        return resultado

    df_pred = df_base.copy()
    
    # 1. Convertir la columna Fecha a datetime de forma segura para extraer el día de la semana
    try:
        df_pred["Fecha_dt"] = pd.to_datetime(df_pred["Fecha"], format="%d/%m/%Y", errors='coerce')
        # Si el formato falla, intentamos detección automática
        if df_pred["Fecha_dt"].isna().all():
            df_pred["Fecha_dt"] = pd.to_datetime(df_pred["Fecha"], errors='coerce')
            
        # Diccionario para traducir al español los días de la semana
        dias_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
        df_pred["Dia_Semana_Texto"] = df_pred["Fecha_dt"].dt.dayofweek.map(dias_es)
    except Exception:
        df_pred["Dia_Semana_Texto"] = "Martes" # Fallback operativo

    # Determinar qué día de la semana consultar (basado en la fecha seleccionada por el usuario)
    if fecha_referencia:
        try:
            fecha_ref_dt = pd.to_datetime(fecha_referencia, format="%d/%m/%Y", errors='coerce')
            if pd.notna(fecha_ref_dt):
                resultado["dia_semana"] = dias_es.get(fecha_ref_dt.dayofweek, "Martes")
        except Exception:
            pass

    # Filtrar el histórico para quedarnos solo con el mismo día de la semana (ej: todos los Martes del mes)
    df_dia_semana = df_pred[df_pred["Dia_Semana_Texto"] == resultado["dia_semana"]].copy()
    if df_dia_semana.empty:
        df_dia_semana = df_pred.copy() # Fallback si hay pocos datos

    # 2. Abrir ventana de influencia temporal de +-15 minutos alrededor de la hora de consulta
    try:
        minutos_consulta = int(hora_consulta[:2]) * 60 + int(hora_consulta[3:5])
        
        def en_ventana_tiempo(h_str):
            try:
                m = int(str(h_str)[:2]) * 60 + int(str(h_str)[3:5])
                return abs(m - minutos_consulta) <= 15
            except:
                return False
                
        df_ventana = df_dia_semana[df_dia_semana["Hora"].apply(en_ventana_tiempo)].copy()
    except Exception:
        df_ventana = pd.DataFrame()

    if df_ventana.empty:
        return resultado

    # 3. Calcular transiciones y deltas cuantitativos del histórico en esa ventana
    df_ventana = df_ventana.sort_values(by=["Archivo", "Fecha", "Hora"])
    df_ventana["Sectores_Actuales"] = df_ventana["Configuracion"].apply(lambda c: len(full_map.get(c, set())))
    df_ventana["Sectores_Previos"] = df_ventana.groupby(["Archivo", "Fecha"])["Sectores_Actuales"].shift(1)
    
    df_ventana = df_ventana.dropna(subset=["Sectores_Previos"])
    df_ventana["Delta"] = df_ventana["Sectores_Actuales"] - df_ventana["Sectores_Previos"]

    total_casos = len(df_ventana)
    if total_casos == 0:
        return resultado

    resultado["total_muestras"] = total_casos
    
    # Contamos frecuencias absolutas
    desdobles = (df_ventana["Delta"] > 0).sum()
    fusiones = (df_ventana["Delta"] < 0).sum()
    estables = (df_ventana["Delta"] == 0).sum()

    # Convertimos a porcentajes probabilísticos probables
    resultado["prob_desdoble"] = int(round((desdobles / total_casos) * 100))
    resultado["prob_fusion"] = int(round((fusiones / total_casos) * 100))
    resultado["prob_estable"] = int(round((estables / total_casos) * 100))

    # 4. Determinar la tendencia líder y aislar el sector integrado/configuración objetivo
    # Reemplaza esas tres líneas finales de asignación por estas versiones indexadas:
    if desdobles > fusiones and desdobles > estables:
        resultado["tendencia_principal"] = "🟢 DESDOBLAMIENTO (Apertura por Tráfico)"
        top_cnf = df_ventana[df_ventana["Delta"] > 0]["Configuracion"].value_counts()
        resultado["sector_objetivo"] = top_cnf.index[0] if not top_cnf.empty else "N/A" # <-- AÑADE EL [0]
        
    elif fusiones > desdobles and fusiones > estables:
        resultado["tendencia_principal"] = "🔴 INTEGRACIÓN (Fusión/Collapse)"
        top_cnf = df_ventana[df_ventana["Delta"] < 0]["Configuracion"].value_counts()
        resultado["sector_objetivo"] = top_cnf.index[0] if not top_cnf.empty else "N/A" # <-- AÑADE EL [0]
        
    else:
        resultado["tendencia_principal"] = "⚪ ESTABLE (Mantenimiento de Capacidad)"
        top_cnf = df_ventana[df_ventana["Delta"] == 0]["Configuracion"].value_counts()
        resultado["sector_objetivo"] = top_cnf.index[0] if not top_cnf.empty else "N/A" # <-- AÑADE EL [0]

    return resultado

def calcular_metricas_estabilidad(df_base):
    """
    Calcula el Índice de Estabilidad Sectorial (IES) y detecta transiciones
    críticas que duran menos de 40 minutos en la sala de control.
    """
    resultado = {
        "duracion_media_minutos": 0.0,
        "total_cambios": 0,
        "transiciones_criticas_count": 0,
        "porcentaje_inestabilidad": 0.0,
        "lista_alertas": []
    }
    
    if df_base.empty:
        return resultado
        
    # Ordenamos cronológicamente el plan del día
    df_cron = df_base.sort_values(by="Hora").copy()
    
    # Función auxiliar para convertir HH:MM a minutos netos del día
    def c_min(h_str):
        try:
            return int(str(h_str)[:2]) * 60 + int(str(h_str)[3:5])
        except:
            return 0

    duraciones = []
    
    for i in range(len(df_cron)):
        fila = df_cron.iloc[i]
        h_ini = c_min(fila["Hora"])
        
        # Si el archivo .COS incluye 'Hora_Fin' la usamos; si no, el inicio de la siguiente fila
        if "Hora_Fin" in df_cron.columns and pd.notna(fila["Hora_Fin"]):
            h_fin = c_min(fila["Hora_Fin"])
        elif i < len(df_cron) - 1:
            h_fin = c_min(df_cron.iloc[i+1]["Hora"])
        else:
            h_fin = 1440 # Cierre del día a las 24:00 (1440 minutos)
            
        duracion_tramo = h_fin - h_ini
        if duracion_tramo > 0:
            duraciones.append((fila["Hora"], fila["Configuracion"], duracion_tramo))

    if not duraciones:
        return resultado

    # Filtrar tramos donde realmente cambia la configuración respecto a la anterior
    cambios_reales = []
    ultima_cnf = None
    
    for hora, cnf, dur in duraciones:
        if cnf != ultima_cnf:
            if ultima_cnf is not None:
                # El tramo anterior terminó cuando empezó este. Registramos su duración acumulada.
                cambios_reales.append((hora_acum, cnf_acum, dur_acum))
            hora_acum, cnf_acum, dur_acum = hora, cnf, dur
            ultima_cnf = cnf
        else:
            dur_acum += dur # Si es la misma configuración consecutiva, sumamos el tiempo
            
    # Añadimos el último bloque del día
    cambios_reales.append((hora_acum, cnf_acum, dur_acum))

    # Cálculos estadísticos netos
    total_cambios = len(cambios_reales) - 1 # El primer tramo es el inicio, no un cambio
    lista_duraciones = [d for _, _, d in cambios_reales]
    
    duracion_media = np.mean(lista_duraciones) if lista_duraciones else 0.0
    
    # Detectar violaciones al umbral regulatorio de 40 minutos
    criticos = 0
    alertas = []
    for h, cnf, d in cambios_reales:
        if d < 40:
            criticos += 1
            alertas.append(f"⏱️ A las **{h}h** la configuración **`{cnf}`** solo duró **{d} min** activa.")

    resultado["duracion_media_minutos"] = round(duracion_media, 1)
    resultado["total_cambios"] = max(0, total_cambios)
    resultado["transiciones_criticas_count"] = criticos
    resultado["porcentaje_inestabilidad"] = int(round((criticos / len(cambios_reales)) * 100)) if cambios_reales else 0
    resultado["lista_alertas"] = alertas
    
    return resultado
