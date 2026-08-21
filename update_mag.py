import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.grupoguarino.com.ar/precios-mag/"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
SOURCE_ID = "guarino-max-corriente2-grupos-v4"

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
    def indice(etiqueta):
        patron = rf"{etiqueta}\s*([\d.]+,\d{{3}})\s*([+-]\d+(?:,\d+)?)%"
        match = re.search(patron, texto, re.IGNORECASE)
        if not match:
            return None, None
        return numero_argentino(match.group(1)), float(match.group(2).replace(",", "."))

    inmag, inmag_change = indice("INMAG")
    igmag, igmag_change = indice("IGMAG")
    arr_match = re.search(r"([\d.]+,\d{2,3})\s*Índice\s+Arrendamiento", texto, re.IGNORECASE)
    arrendamiento = numero_argentino(arr_match.group(1)) if arr_match else None
    arr_change_match = re.search(r"Índice\s+Arrendamiento\s*([+-]\d+(?:,\d+)?)%\s*Var\.\s*Arrendamiento", texto, re.IGNORECASE)
    arr_change = float(arr_change_match.group(1).replace(",", ".")) if arr_change_match else None
    return {
        "inmag_novillo": inmag,
        "igmag_general": igmag,
        "arrendamiento": arrendamiento,
    }, {
        "inmag_novillo": inmag_change,
        "igmag_general": igmag_change,
        "arrendamiento": arr_change,
    }


def extraer_corriente_maximo(texto, nombre):
    precio = r"(?:\$\s*)?([0-9][0-9.]*(?:,[0-9]+)?|—)"
    patron = re.escape(nombre) + rf"\s+{precio}\s+{precio}\s+{precio}"
    match = re.search(patron, texto, re.IGNORECASE)
    return numero_argentino(match.group(2)) if match else None


def obtener_fecha(texto):
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
        "julio": "07", "agosto": "08", "septiembre": "09", "setiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    patrones = [
        r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",
        r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})",
        r"(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{4})",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if not match:
            continue
        grupos = match.groups()
        if len(grupos) == 3 and grupos[1].lower() in meses:
            return f"{grupos[0].zfill(2)}/{meses[grupos[1].lower()]}/{grupos[2]}"
        return f"{grupos[0].zfill(2)}/{grupos[1].zfill(2)}/{grupos[2]}"
    return None


def promedio_grupo(valores, claves):
    disponibles = [valores.get(clave) for clave in claves if valores.get(clave) is not None]
    return round(sum(disponibles) / len(disponibles), 2) if disponibles else None


def obtener_ultima_rueda():
    html = obtener_pagina()
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)
    fecha_publicada = obtener_fecha(texto)
    entrada_match = re.search(r"Entrada del día\s+([\d.]+)\s+Cabezas", texto, re.IGNORECASE)
    cabezas = int(entrada_match.group(1).replace(".", "")) if entrada_match else None
    valores = {clave: extraer_corriente_maximo(texto, nombre) for clave, nombre in CATEGORIAS.items()}
    if not fecha_publicada:
        raise RuntimeError("No se pudo determinar la fecha de la rueda MAG en Guarino")
    if all(valor is None for valor in valores.values()):
        raise RuntimeError("No se encontraron las categorías de precios MAG en Guarino")
    indices, indices_changes = obtener_indices(texto)
    faltantes = [clave for clave, valor in indices.items() if valor is None]
    if faltantes:
        raise RuntimeError(f"No se encontraron los índices MAG: {', '.join(faltantes)}")
    grupos = {nombre: promedio_grupo(valores, claves) for nombre, claves in GRUPOS.items()}
    return fecha_publicada, valores, grupos, cabezas, indices, indices_changes


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
    fecha_publicada, valores, grupos, cabezas, indices, indices_changes = obtener_ultima_rueda()
    anterior = cargar_anterior()
    if fecha_publicada == anterior.get("date") and anterior.get("source_id") == SOURCE_ID:
        print(f"MAG: sin rueda nueva ({fecha_publicada}). Se conservan mag.json y mag_previous.json.")
        return
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
        "group_values": grupos,
        "values": valores,
        "changes": {clave: None for clave in grupos},
        "indices": indices,
        "indices_changes": indices_changes,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)
    with open(STATE_FILE, "w", encoding="utf-8") as archivo:
        json.dump({"source_id": SOURCE_ID, "values": valores, "group_values": grupos, "heads": cabezas, "date": fecha_publicada, "indices": indices}, archivo, ensure_ascii=False, indent=2)
    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
