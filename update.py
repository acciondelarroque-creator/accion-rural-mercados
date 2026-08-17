import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


URL = "https://news.agrofy.com.ar/granos/precios-pizarra"


def limpiar_numero(valor):
    if not valor:
        return None

    valor = valor.replace("$", "")
    valor = valor.replace(".", "")
    valor = valor.replace(",", ".")

    try:
        return float(valor)
    except ValueError:
        return None


def buscar_precio(texto, producto):
    patron = rf"{producto}.{{0,300}}?\$?\s*([0-9][0-9\.,]*)"

    resultado = re.search(
        patron,
        texto,
        flags=re.IGNORECASE | re.DOTALL
    )

    if not resultado:
        return None

    return limpiar_numero(resultado.group(1))


def main():

    respuesta = requests.get(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=30
    )

    respuesta.raise_for_status()

    soup = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    texto = soup.get_text(
        " ",
        strip=True
    )

    precios = {
        "soja": buscar_precio(texto, "soja"),
        "maiz": buscar_precio(texto, "maíz|maiz"),
        "trigo": buscar_precio(texto, "trigo"),
        "girasol": buscar_precio(texto, "girasol"),
        "sorgo": buscar_precio(texto, "sorgo")
    }

    datos = {
        "actualizado": datetime.now(
            timezone.utc
        ).isoformat(),

        "fuente": "Agrofy News",

        "url": URL,

        "precios": precios
    }

    with open(
        "data.json",
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            datos,
            archivo,
            ensure_ascii=False,
            indent=2
        )

    print(json.dumps(
        datos,
        ensure_ascii=False,
        indent=2
    ))


if __name__ == "__main__":
    main()
