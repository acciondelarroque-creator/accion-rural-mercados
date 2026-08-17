import json
import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


URL = "https://www.bcr.com.ar/es/mercados/mercado-de-granos/cotizaciones/cotizaciones-locales-0"


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").lower().strip()


def limpiar_numero(valor):
    if not valor:
        return None

    valor = valor.strip()

    if "S/C" in valor.upper():
        return None

    valor = valor.replace("$", "").replace("US$", "")
    valor = valor.replace(" ", "")
    valor = valor.replace(".", "")
    valor = valor.replace(",", ".")

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

    filas = tabla.find_all("tr")

    fecha = None
    valores = {}

    nombres = {
        "soja": "soja",
        "sorgo": "sorgo",
        "girasol": "girasol",
        "trigo": "trigo",
        "maiz": "maiz"
    }

    for fila in filas:
        celdas = fila.find_all(["th", "td"])
        textos = [c.get_text(" ", strip=True) for c in celdas]

        if not textos:
            continue

        fila_normalizada = [normalizar(t) for t in textos]

        if "fecha negociacion" in fila_normalizada[0]:
            fechas = re.findall(r"\d{2}/\d{2}/\d{4}", " ".join(textos))
            if fechas:
                fecha = fechas[0]
            continue

        producto = fila_normalizada[0]

        clave = None
        for nombre_normalizado, clave_producto in nombres.items():
            if producto == nombre_normalizado or producto.startswith(nombre_normalizado + " "):
                clave = clave_producto
                break

        if clave is None or len(textos) < 3:
            continue

        valores[clave] = limpiar_numero(textos[2])

    requeridos = ["soja", "maiz", "trigo", "girasol", "sorgo"]

    if not any(valores.get(k) is not None for k in requeridos):
        raise RuntimeError("La BCR no devolvió precios reconocibles")

    return fecha, {k: valores.get(k) for k in requeridos}


def main():
    respuesta = requests.get(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"
        },
        timeout=30
    )

    respuesta.raise_for_status()

    soup = BeautifulSoup(respuesta.text, "html.parser")

    fecha, valores = obtener_precios(soup)

    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Bolsa de Comercio de Rosario - Cámara Arbitral de Cereales",
        "url": URL,
        "date": fecha,
        "values": valores
    }

    with open("data.json", "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
