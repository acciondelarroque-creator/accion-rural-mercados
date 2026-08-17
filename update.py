import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = "https://granos.ar/"

PRODUCTOS = {
    "soja": "Soja",
    "maiz": "Maíz",
    "trigo": "Trigo",
    "girasol": "Girasol",
    "sorgo": "Sorgo"
}


def obtener_precio(texto, producto):

    patron = (
        re.escape(producto)
        + r".{0,500}?\$([0-9][0-9.]*)"
        + r"(?:,[0-9]+)?\s*/tn"
    )

    resultado = re.search(
        patron,
        texto,
        flags=re.IGNORECASE | re.DOTALL
    )

    if not resultado:
        return None

    valor = resultado.group(1)

    valor = valor.replace(".", "")

    try:
        return int(valor)
    except ValueError:
        return None


def main():

    respuesta = requests.get(
        URL,
        timeout=30,
        headers={
            "User-Agent":
            "AccionRuralMercados/1.0"
        }
    )

    respuesta.raise_for_status()

    sopa = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    texto = sopa.get_text(
        " ",
        strip=True
    )


    valores = {}

    for clave, producto in PRODUCTOS.items():

        valores[clave] = obtener_precio(
            texto,
            producto
        )


    encontrados = sum(
        1
        for valor in valores.values()
        if valor is not None
    )


    if encontrados < 3:

        raise RuntimeError(
            "No se pudieron obtener suficientes precios: "
            + str(valores)
        )


    fecha = None

    resultado_fecha = re.search(
        r"Precios de Pizarra CAC.*?"
        r"(\d{2}/\d{2}/\d{4})",
        texto,
        flags=re.IGNORECASE | re.DOTALL
    )

    if resultado_fecha:

        fecha = resultado_fecha.group(1)


    datos = {

        "ok": True,

        "source":
        "granos.ar / CAC-BCR",

        "source_url":
        URL,

        "date":
        fecha,

        "values":
        valores,

        "updated_at":
        datetime.now(
            timezone.utc
        ).isoformat()

    }


    Path("data.json").write_text(

        json.dumps(
            datos,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"

    )


if __name__ == "__main__":

    main()
