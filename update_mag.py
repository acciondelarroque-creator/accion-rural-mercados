import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.grupoguarino.com.ar/precios-mag/"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
CATEGORIAS = {
    "novillos": "NOVILLOS",
    "novillitos": "NOVILLITOS",
    "vaquillonas": "VAQUILLONAS",
    "vacas": "VACAS",
    "toros": "TOROS",
}


def limpiar_token(token):
    return re.sub(r"\s+", " ", token.strip())


def numero_argentino(token):
    token = limpiar_token(token).replace("$", "")
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


def encontrar_tabla(soup):
    for tabla in soup.find_all("table"):
        texto = tabla.get_text(" ", strip=True).upper()
        if "MÍN." in texto and "CORRIENTE" in texto and "MÁXIMOS" in texto:
            return tabla
    return None


def obtener_ultima_rueda():
    html = obtener_pagina()
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text(" ", strip=True)

    fecha_match = re.search(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", texto, re.IGNORECASE)
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    fecha_publicada = None
    if fecha_match:
        dia, mes, anio = fecha_match.groups()
        numero_mes = meses.get(mes.lower())
        if numero_mes:
            fecha_publicada = f"{dia.zfill(2)}/{numero_mes}/{anio}"

    entrada_match = re.search(r"Entrada del día\s+([\d.]+)\s+Cabezas", texto, re.IGNORECASE)
    cabezas = int(entrada_match.group(1).replace(".", "")) if entrada_match else None

    tabla = encontrar_tabla(soup)
    if tabla is None:
        raise RuntimeError("No se encontró la tabla de precios MAG en Guarino")

    valores = {clave: None for clave in CATEGORIAS}
    categoria_actual = None

    for fila in tabla.find_all("tr"):
        celdas = [limpiar_token(c.get_text(" ", strip=True)) for c in fila.find_all(["th", "td"])]
        if not celdas:
            continue

        primera = celdas[0].upper()
        for clave, nombre in CATEGORIAS.items():
            if primera == nombre:
                categoria_actual = clave
                break

        if categoria_actual is None or len(celdas) < 4:
            continue

        # Guarino: Categoría | Mín. Corriente | Máx. Corriente | Máximos | Kilos
        # Usamos Máx. Corriente, es decir, "Corriente 2".
        valor = numero_argentino(celdas[2])
        if valor is not None:
            if valores[categoria_actual] is None or valor > valores[categoria_actual]:
                valores[categoria_actual] = valor

    if not fecha_publicada:
        raise RuntimeError("No se pudo determinar la fecha de la rueda MAG")
    if all(valor is None for valor in valores.values()):
        raise RuntimeError("La tabla MAG de Guarino no contiene valores de Máx. Corriente")

    return fecha_publicada, valores, cabezas


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
    fecha_publicada, valores, cabezas = obtener_ultima_rueda()
    anterior = cargar_anterior()

    if fecha_publicada == anterior.get("date"):
        print(f"MAG: sin rueda nueva ({fecha_publicada}). Se conservan mag.json y mag_previous.json.")
        return

    cambios = calcular_variaciones(valores, anterior.get("values", {}))
    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Guarino Producciones · Mercado Agroganadero de Cañuelas (MAG)",
        "url": BASE_URL,
        "date": fecha_publicada,
        "heads": cabezas,
        "values": valores,
        "changes": cambios,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)
    with open(STATE_FILE, "w", encoding="utf-8") as archivo:
        json.dump({"values": valores, "heads": cabezas, "date": fecha_publicada}, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
