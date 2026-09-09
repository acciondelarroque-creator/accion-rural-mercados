import json
import os
import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

LOCAL_URL = "https://www.bcr.com.ar/es/mercados/mercado-de-granos/cotizaciones/cotizaciones-locales-0"
CHICAGO_URL = "https://www.bcr.com.ar/es/mercados/mercado-de-granos/cotizaciones/cotizaciones-internacionales-1"
STATE_FILE = "previous.json"
OUTPUT_FILE = "data.json"


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").lower().strip()


def limpiar_numero(valor):
    if not valor:
        return None
    valor = valor.strip()
    if "S/C" in valor.upper():
        return None
    valor = valor.replace("US$", "").replace("$", "").replace(" ", "")
    valor = valor.replace(".", "").replace(",", ".")
    try:
        return float(valor)
    except ValueError:
        return None


def cargar_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return {}


def calcular_variaciones(actual, anterior):
    resultado = {}
    for clave, valor in actual.items():
        previo = anterior.get(clave)
        if valor is None or previo is None or previo == 0:
            resultado[clave] = None
        else:
            resultado[clave] = round((valor - previo) / previo * 100, 2)
    return resultado


def obtener_precios(soup):
    tabla = None
    for table in soup.find_all("table"):
        texto = normalizar(table.get_text(" ", strip=True))
        if "soja" in texto and "trigo" in texto and "maiz" in texto:
            tabla = table
            break
    if tabla is None:
        raise RuntimeError("No se encontró la tabla de cotizaciones de la BCR")

    fechas = re.findall(r"\d{2}/\d{2}/\d{4}", tabla.get_text(" ", strip=True))
    fecha = max(fechas, key=lambda f: datetime.strptime(f, "%d/%m/%Y")) if fechas else None

    nombres = {"soja": "soja", "sorgo": "sorgo", "girasol": "girasol", "trigo": "trigo", "maiz": "maiz"}
    valores = {}
    for fila in tabla.find_all("tr"):
        textos = [c.get_text(" ", strip=True) for c in fila.find_all(["th", "td"])]
        if len(textos) < 3:
            continue
        producto = normalizar(textos[0])
        clave = next((v for k, v in nombres.items() if producto == k or producto.startswith(k + " ")), None)
        if clave:
            valores[clave] = limpiar_numero(textos[2])

    requeridos = ["soja", "maiz", "trigo", "girasol", "sorgo"]
    if not any(valores.get(k) is not None for k in requeridos):
        raise RuntimeError("La BCR no devolvió precios reconocibles")
    return fecha, {k: valores.get(k) for k in requeridos}


def obtener_chicago(soup):
    tabla = None
    for table in soup.find_all("table"):
        texto = normalizar(table.get_text(" ", strip=True))
        if "trigo chicago" in texto and "maiz chicago" in texto and "soja chicago" in texto:
            tabla = table
            break
    if tabla is None:
        raise RuntimeError("No se encontró la tabla Chicago/Kansas de la BCR")

    texto_tabla = tabla.get_text(" ", strip=True)
    fechas = re.findall(r"\d{2}/\d{2}/\d{4}", texto_tabla)
    fecha = max(fechas, key=lambda f: datetime.strptime(f, "%d/%m/%Y")) if fechas else None

    # Posiciones de referencia acordadas para la marquesina.
    referencias_fijas = {
        "soja": "Nov-26",
        "maiz": "Dic-26",
        "trigo": "Dic-26",
    }

    filas = {}
    for fila in tabla.find_all("tr"):
        celdas = fila.find_all(["th", "td"])
        textos = [c.get_text(" ", strip=True) for c in celdas]
        if not textos:
            continue
        posicion = textos[0]
        if not re.match(r"^[A-Z][a-z]{2}-\d{2}$", posicion):
            continue
        numeros = [limpiar_numero(t) for t in textos[1:]]
        numeros = [n for n in numeros if n is not None]
        filas[posicion] = numeros

    referencias = {}
    for producto, etiqueta in referencias_fijas.items():
        numeros = filas.get(etiqueta, [])
        precio = None
        variacion = None

        if etiqueta == "Nov-26" and producto == "soja":
            # Nov-26: solo aparece la cotización de Soja.
            if len(numeros) >= 2:
                precio, variacion = numeros[0], numeros[1]

        elif etiqueta == "Dic-26":
            # En Dic-26, BCR presenta en este orden:
            # Trigo Chicago/1: 274,48 / 4,87
            # Trigo Chicago/2: 300,94 / 6,43
            # Maíz Chicago/3: 210,03 / -1,57
            # Para la marquesina usamos Trigo Chicago/2 y Maíz Chicago/3.
            if len(numeros) >= 6:
                pares = {
                    "trigo": (numeros[2], numeros[3]),
                    "maiz": (numeros[4], numeros[5]),
                }
                precio, variacion = pares[producto]

        referencias[producto] = {"contract": etiqueta, "value": precio, "change": variacion}

    faltantes = [k for k, v in referencias.items() if v["value"] is None]
    if faltantes:
        raise RuntimeError("No se pudieron obtener las posiciones Chicago de referencia: " + ", ".join(faltantes))

    return fecha, referencias


def main():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}

    local_response = requests.get(LOCAL_URL, headers=headers, timeout=30)
    local_response.raise_for_status()
    fecha_local, valores = obtener_precios(BeautifulSoup(local_response.text, "html.parser"))

    chicago_response = requests.get(CHICAGO_URL, headers=headers, timeout=30)
    chicago_response.raise_for_status()
    fecha_chicago, chicago = obtener_chicago(BeautifulSoup(chicago_response.text, "html.parser"))

    anterior_estado = cargar_json(STATE_FILE)
    anterior = anterior_estado.get("values", {})
    fecha_anterior = anterior_estado.get("date")

    datos = cargar_json(OUTPUT_FILE) if fecha_local and fecha_local == fecha_anterior else {}
    if not datos:
        datos = {
            "source": "Bolsa de Comercio de Rosario - Cámara Arbitral de Cereales",
            "url": LOCAL_URL,
            "date": fecha_local,
            "values": valores,
            "changes": calcular_variaciones(valores, anterior)
        }

    datos["updated"] = datetime.now(timezone.utc).isoformat()
    datos["chicago"] = {
        "source": "BCR - Chicago/Kansas (CME Group)",
        "url": CHICAGO_URL,
        "date": fecha_chicago,
        "values": {k: v["value"] for k, v in chicago.items()},
        "changes": {k: v["change"] for k, v in chicago.items()},
        "contracts": {k: v["contract"] for k, v in chicago.items()}
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)

    if fecha_local != fecha_anterior:
        with open(STATE_FILE, "w", encoding="utf-8") as archivo:
            json.dump({"values": valores, "date": fecha_local}, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
