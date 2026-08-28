import json
import os
import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


URL = "https://www.bcr.com.ar/es/mercados/mercado-de-granos/cotizaciones/cotizaciones-locales-0"
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
    valor = valor.replace("$", "").replace("US$", "").replace(" ", "")
    valor = valor.replace(".", "").replace(",", ".")
    try:
        return float(valor)
    except ValueError:
        return None


def obtener_precios(soup):
    tabla = None
    for table in soup.find_all("table"):
        texto = normalizar(table.get_text(" ", strip=True))
        if "soja" in texto and "trigo" in texto and "maiz" in texto:
            tabla = table
            break
    if tabla is None:
        raise RuntimeError("No se encontró la tabla de cotizaciones de la BCR")

    # La BCR puede cambiar el orden de las celdas del encabezado.
    # No tomar simplemente la primera fecha encontrada: elegir la fecha
    # más reciente de las que aparecen en la tabla.
    fechas_en_tabla = re.findall(r"\d{2}/\d{2}/\d{4}", tabla.get_text(" ", strip=True))
    fecha = max(fechas_en_tabla, key=lambda f: datetime.strptime(f, "%d/%m/%Y")) if fechas_en_tabla else None

    valores = {}
    nombres = {"soja": "soja", "sorgo": "sorgo", "girasol": "girasol", "trigo": "trigo", "maiz": "maiz"}

    for fila in tabla.find_all("tr"):
        celdas = fila.find_all(["th", "td"])
        textos = [c.get_text(" ", strip=True) for c in celdas]
        if not textos:
            continue

        fila_normalizada = [normalizar(t) for t in textos]
        producto = fila_normalizada[0]
        clave = None
        for nombre_normalizado, clave_producto in nombres.items():
            if producto == nombre_normalizado or producto.startswith(nombre_normalizado + " "):
                clave = clave_producto
                break

        if clave is None or len(textos) < 3:
            continue

        # La primera cotización está en la tercera celda (después del
        # nombre en español y su traducción al inglés).
        valores[clave] = limpiar_numero(textos[2])

    requeridos = ["soja", "maiz", "trigo", "girasol", "sorgo"]
    if not any(valores.get(k) is not None for k in requeridos):
        raise RuntimeError("La BCR no devolvió precios reconocibles")
    return fecha, {k: valores.get(k) for k in requeridos}


def cargar_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return {}


def calcular_variaciones(actual, anterior):
    variaciones = {}
    for clave, valor in actual.items():
        previo = anterior.get(clave)
        if valor is None or previo is None or previo == 0:
            variaciones[clave] = None
        else:
            variaciones[clave] = round((valor - previo) / previo * 100, 2)
    return variaciones


def main():
    respuesta = requests.get(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}, timeout=30)
    respuesta.raise_for_status()
    fecha, valores = obtener_precios(BeautifulSoup(respuesta.text, "html.parser"))

    anterior_estado = cargar_json(STATE_FILE)
    anterior = anterior_estado.get("values", {})
    fecha_anterior = anterior_estado.get("date")

    # Si la BCR todavía no publicó una rueda nueva, no tocar nada.
    if fecha and fecha_anterior and fecha == fecha_anterior:
        print(f"BCR: sin rueda nueva ({fecha}). Se conservan data.json y previous.json.")
        return

    variaciones = calcular_variaciones(valores, anterior)

    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Bolsa de Comercio de Rosario - Cámara Arbitral de Cereales",
        "url": URL,
        "date": fecha,
        "values": valores,
        "changes": variaciones
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)

    with open(STATE_FILE, "w", encoding="utf-8") as archivo:
        json.dump({"values": valores, "date": fecha}, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
