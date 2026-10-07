import io
import pandas as pd


def parse_cos_content(file_bytes, filename=""):
    """Parseador consolidado para ficheros .COS estructurados por punto y coma (;).

    Formato esperado: Fecha;ACC;Hora_Ini;Hora_Fin;Configuracion;Tipo
    Ejemplo: 11/06/2026;LECMCTAS;04:45;05:05;CNF3C;E
    """
    try:
        text = file_bytes.decode("latin-1", errors="ignore")
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and not line.startswith("#")
            and not line.startswith(";")
        ]

        records = []

        for line in lines:
            parts = [p.strip().upper() for p in line.split(";")]

            # Si la línea tiene al menos 5 campos delimitados por ';'
            if len(parts) >= 5:
                fecha = parts[0]
                acc = parts[1]
                h_ini = parts[2]
                h_fin = parts[3]
                cfg = parts[4]
                tipo = parts[5] if len(parts) > 5 else "E"

                try:
                    t_ini = pd.to_datetime(h_ini, format="%H:%M")
                    t_fin = pd.to_datetime(h_fin, format="%H:%M")

                    # Manejo del solape de medianoche (ej. 23:30 a 01:15)
                    if t_fin <= t_ini:
                        t_fin += pd.Timedelta(days=1)

                    dur_min = (t_fin - t_ini).total_seconds() / 60.0
                    dur_h = dur_min / 60.0

                    records.append(
                        {
                            "ACC": acc,
                            "Fecha": fecha,
                            "Hora Inicio": h_ini,
                            "Hora Fin": h_fin,
                            "Configuración": cfg,
                            "Tipo": tipo,
                            "Duración (min)": dur_min,
                            "Duración (h)": dur_h,
                            "Archivo": filename,
                            "Linea_Original": line,
                        }
                    )
                except Exception:
                    continue

        return pd.DataFrame(records)

    except Exception:
        return pd.DataFrame()


def parse_spc_content(file_bytes, filename=""):
    """Parseador consolidado para estructura de sectores (.SPC).

    Parsea la jerarquía de Sectores Integrados (CS) a Sectores Elementales (ES).
    Formato esperado:
      A;LECSNCS;_;CS;7   -> Define la cabecera del CS
      S;LECSALCU;ES      -> Define un Sector Elemental (ES) asociado al CS
    activo
    """
    text = file_bytes.decode("latin-1", errors="ignore")
    spc_map = {}
    current_cs = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        parts = [p.strip().upper() for p in line.split(";") if p.strip()]
        if not parts:
            continue

        # Detección de Cabecera CS (ej: A;LECSNCS;_;CS;7)
        if parts[0] == "A" and len(parts) >= 2:
            current_cs = parts[1]
            if current_cs not in spc_map:
                spc_map[current_cs] = set()

        # Detección de Sector Elemental ES (ej: S;LECSALCU;ES)
        elif parts[0] == "S" and len(parts) >= 2 and current_cs:
            es_name = parts[1]
            spc_map[current_cs].add(es_name)

    # Convertir conjuntos a listas ordenadas
    spc_map_sorted = {
        cs: sorted(list(es_set)) for cs, es_set in spc_map.items()
    }

    return {"filename": filename, "cs_es_map": spc_map_sorted}


def parse_cfg_content(file_bytes, filename=""):
    """Parseador consolidado para definiciones de configuraciones (.CFG).

    Formato esperado: ACC;Configuracion;Sector
    Ejemplo: LECBCTAW;CNF4CW;LECBG23
    """
    text = file_bytes.decode("latin-1", errors="ignore")
    acc_to_cnf = {}
    cnf_to_sectors = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        parts = [p.strip().upper() for p in line.split(";") if p.strip()]

        if len(parts) >= 3:
            acc = parts[0]
            cnf = parts[1]
            sector = parts[2]

            acc_to_cnf.setdefault(acc, set()).add(cnf)
            cnf_to_sectors.setdefault(cnf, set()).add(sector)

    # Convertir conjuntos a listas ordenadas
    acc_to_cnf_sorted = {
        acc: sorted(list(cnfs)) for acc, cnfs in acc_to_cnf.items()
    }
    cnf_to_sectors_sorted = {
        cnf: sorted(list(sectors)) for cnf, sectors in cnf_to_sectors.items()
    }

    return {
        "filename": filename,
        "acc_to_cnf": acc_to_cnf_sorted,
        "cnf_to_sectors": cnf_to_sectors_sorted,
    }