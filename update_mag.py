import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.grupoguarino.com.ar/precios-mag/"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
SOURCE_ID = "guarino-max-corriente2-categorias-v2"

CATEGORIAS = {
    "novillos_431_460": "Novillos 431/460",
    "novillos_461_490": "Novillos 461/490",
    "novillos_491_520": "Novillos 491/520",
    "novillos_mas_520": "Novillos +520",
    "novillos_regulares": "Novillos regulares",
    "novillitos_300_350": "Novillitos 300/350",
    "novillitos_351_390": "Novillitos 351/390",
    "novillitos_391_430": "Novillitos 391/430",
    "novillitos_regulares": "Novillitos regulares",
    "vaquillonas_300_350": "Vaquillonas 300/350",
    "vaquillonas_351_390": "Vaquillonas 351/390",
    "vaquillonas_391_430": "Vaquillonas 391/430",
    "vaquillonas_regulares": "Vaquillonas regulares",
    "vacas_buenas_especiales": "Vacas (buenas a especiales)",
    "vacas_regulares": "Vacas regulares",
    "toros_buenos_especiales": "Toros (buenos a especiales)",
    "toros_regulares": "Toros regulares",
}

GRUPOS = {
    "NOVILLOS": ["novillos_431_460", "novillos_461_490", "novillos_491_520", "novillos_mas_520", "novillos_regulares"],
    "NOVILLITOS": ["novillitos_300_350", "novillitos_351_390", "novillitos_391_430", "novillitos_regulares"],
    "VAQUILLONAS": ["vaquillonas_300_350", "vaquillonas_351_390", "vaquillonas_391_430", "vaquillonas_regulares"],
    "VACAS": ["vacas_buenas_especiales", "vacas_regulares"],
    "TOROS": ["toros_buenos_especiales", "toros_regulares"],
}


def limpiar_token(token):
    return re.sub(r"\s+", " ", token.strip())


def numero_argentino(token):
    if token is None:
        return None
    token = limpiar_token(token).replace("$", "")
    if token in {"", "—", "-"}:
        return None
    token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def obtener_pagina():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}
    respuesta = requests.get(BASE_URL, headers=headers, timeout=30)
    respuesta.raise_for_status()
    return respuesta.text


def obtener_indices(texto):
    # Guarino actualmente publica los índices en la cabecera como:
    # INMAG 4.312,210+0,0%Índice de Novillo
    # IGMAG 3.680,250-1,4%Índice General
    def indice(etiqueta):
        patron = rf"{etiqueta}\s*([\d.]+,\d{{3}})\s*([+-]\d+(?:,\d+)?)%"
        match = re.search(patron, texto, re.IGNORECASE)
        if not match:
            return None, None
        return numero_argentino(match.group(1)), float(match.group(2).replace(",", "."))

    inmag, inmag_change = indice("INMAG")
    igmag, igmag_change = indice("IGMAG")

    arr = re.search(
        r"([\d.]+,\d{2,3})\s+Índice Arrendamiento\s+([+-]\d+(?:,\d+)?)%Var\. Arrendamiento",
        texto,
        re.IGNORECASE,
    )
    if arr:
        arrendamiento = numero_argentino(arr.group(1))
        arr_change = float(arr.group(2).replace(",", "."))
    else:
        arrendamiento = None
        arr_change = None

    indices = {
        "inmag_novillo": inmag,
        "igmag_general": igmag,
        "arrendamiento": arrendamiento,
    }
    changes = {
        "inmag_novillo": inmag_change,
        "igmag_general": igmag_change,
        "arrendamiento": arr_change,
    }
    return indices, changes


def obtener_ultima_rueda():
    html = obtener_pagina()
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)

    fecha_match = re.search(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", texto, re.IGNORECASE)
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
        "julio": "07", "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    fecha_publicada = None
    if fecha_match:
        dia, mes, anio = fecha_match.groups()
        numero_mes = meses.get(mes.lower())
        if numero_mes:
            fecha_publicada = f"{dia.zfill(2)}/{numero_mes}/{anio}"

    entrada_match = re.search(r"Entrada del día\s+([\d.]+)\s+Cabezas", texto, re.IGNORECASE)
    cabezas = int(entrada_match.group(1).replace(".", "")) if entrada_match else None

    tabla = None
    for candidata in soup.find_all("table"):
        encabezado = candidata.get_text(" ", strip=True).upper()
        if "MÍN. CORRIENTE" in encabezado and "MÁX. CORRIENTE" in encabezado:
            tabla = candidata
            break
    if tabla is None:
        raise RuntimeError("No se encontró la tabla de precios MAG en Guarino")

    nombres = {limpiar_token(nombre).upper(): clave for clave, nombre in CATEGORIAS.items()}
    valores = {clave: None for clave in CATEGORIAS}

    for fila in tabla.find_all("tr"):
        celdas = [limpiar_token(c.get_text(" ", strip=True)) for c in fila.find_all(["th", "td"])]
        if len(celdas) < 3:
            continue
        clave = nombres.get(celdas[0].upper())
        if clave is not None:
            # Categoría | Mín. Corriente | Máx. Corriente | Máximos | Kilos
            valores[clave] = numero_argentino(celdas[2])

    if not fecha_publicada:
        raise RuntimeError("No se pudo determinar la fecha de la rueda MAG")
    if all(valor is None for valor in valores.values()):
        raise RuntimeError("La tabla MAG de Guarino no contiene valores de Máx. Corriente")

    indices, indices_changes = obtener_indices(texto)
    if any(valor is None for valor in indices.values()):
        faltantes = [clave for clave, valor in indices.items() if valor is None]
        raise RuntimeError(f"No se encontraron los índices MAG: {', '.join(faltantes)}")

    return fecha_publicada, valores, cabezas, indices, indices_changes


def cargar_anterior():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return {}


def calcular_variaciones(actual, anterior):
    cambios = {}
    for clave, valor in actual.items():
        previo = anterior.get(clave)
        if valor is None or previo is None or previo == 0:
            cambios[clave] = None
        else:
            cambios[clave] = round((valor - previo) / previo * 100, 2)
    return cambios


def main():
    fecha_publicada, valores, cabezas, indices, indices_changes = obtener_ultima_rueda()
    anterior = cargar_anterior()

    if fecha_publicada == anterior.get("date") and anterior.get("source_id") == SOURCE_ID:
        print(f"MAG: sin rueda nueva ({fecha_publicada}). Se conservan mag.json y mag_previous.json.")
        return

    misma_fuente = anterior.get("source_id") == SOURCE_ID
    cambios = calcular_variaciones(valores, anterior.get("values", {})) if misma_fuente else {clave: None for clave in valores}

    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Guarino Producciones · Mercado Agroganadero de Cañuelas (MAG)",
        "url": BASE_URL,
        "date": fecha_publicada,
        "heads": cabezas,
        "label": "Corrientes Máximos",
        "source_field": "Máx. Corriente (Corriente 2)",
        "categories": CATEGORIAS,
        "groups": GRUPOS,
        "values": valores,
        "changes": cambios,
        "indices": indices,
        "indices_changes": indices_changes,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)
    with open(STATE_FILE, "w", encoding="utf-8") as archivo:
        json.dump({
            "source_id": SOURCE_ID,
            "values": valores,
            "heads": cabezas,
            "date": fecha_publicada,
            "indices": indices,
        }, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
