import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.mercadoagroganadero.com.ar/dll/hacienda1.dll/haciinfo000002"
STATE_FILE = "mag_previous.json"
OUTPUT_FILE = "mag.json"
CATEGORIAS = [
    ("novillos", "NOVILLOS"),
    ("novillitos", "NOVILLITOS"),
    ("vaquillonas", "VAQUILLONAS"),
    ("vacas", "VACAS"),
    ("toros", "TOROS"),
]


def url_para_fecha(fecha):
    fecha_txt = fecha.strftime("%d/%m/%Y")
    params = {"LISTADO": "SI", "txtFECHAFIN": fecha_txt, "txtFECHAINI": fecha_txt}
    return BASE_URL + "?" + urlencode(params)


def limpiar_lineas(html):
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text("\n", strip=True)
    lineas = []
    for linea in texto.splitlines():
        linea = re.sub(r"\s+", " ", linea).strip()
        if linea:
            lineas.append(linea)
    return lineas


def numero_argentino(token):
    token = token.strip()
    if not re.fullmatch(r"\d[\d.]*,\d{3}", token):
        return None
    return float(token.replace(".", "").replace(",", "."))


def numero_entero(token):
    token = token.strip().replace(".", "")
    if not re.fullmatch(r"\d+", token):
        return None
    return int(token)


def encontrar_promedios(lineas):
    nombres = [nombre for _, nombre in CATEGORIAS]
    resultados = {}

    for indice, (clave, nombre) in enumerate(CATEGORIAS):
        inicio = next((i for i, linea in enumerate(lineas) if linea.upper().startswith(nombre)), None)
        if inicio is None:
            continue

        siguientes = []
        for siguiente in nombres[indice + 1:]:
            pos = next((i for i in range(inicio + 1, len(lineas)) if lineas[i].upper().startswith(siguiente)), None)
            if pos is not None:
                siguientes.append(pos)
        fin = min(siguientes) if siguientes else len(lineas)

        bloque = lineas[inicio:fin]
        for i, linea in enumerate(bloque[:-1]):
            if linea.replace(" ", "") and set(linea.replace(" ", "")) <= {"-"}:
                tokens = bloque[i + 1].split()
                if tokens:
                    valor = numero_argentino(tokens[0])
                    if valor is not None:
                        resultados[clave] = valor
                        break

    return resultados


def encontrar_cabezas_totales(lineas):
    for i, linea in enumerate(lineas):
        if linea.upper().startswith("TOTALES") and i + 1 < len(lineas):
            tokens = lineas[i + 1].split()
            # La fila de totales tiene: promedio, cabezas, importe, kgs, promedio kgs.
            for posicion in range(len(tokens)):
                valor = numero_entero(tokens[posicion])
                if valor is not None and posicion + 1 < len(tokens):
                    siguiente = tokens[posicion + 1]
                    if siguiente.startswith("$"):
                        return valor
    return None


def extraer_fecha_publicada(lineas):
    for linea in lineas:
        match = re.search(r"DESDE .*? AL .*? (\d{2}/\d{2}/\d{4})", linea, re.IGNORECASE)
        if match:
            return match.group(1)
    for linea in lineas:
        fechas = re.findall(r"\d{2}/\d{2}/\d{4}", linea)
        if fechas and "PRECIOS" in linea.upper():
            return fechas[-1]
    return None


def obtener_ultima_rueda():
    hoy = date.today()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AccionRuralBot/1.0)"}

    for retroceso in range(0, 10):
        fecha = hoy - timedelta(days=retroceso)
        respuesta = requests.get(url_para_fecha(fecha), headers=headers, timeout=30)
        respuesta.raise_for_status()
        lineas = limpiar_lineas(respuesta.text)
        valores = encontrar_promedios(lineas)
        cabezas = encontrar_cabezas_totales(lineas)

        if len(valores) == len(CATEGORIAS) and cabezas is not None:
            fecha_publicada = extraer_fecha_publicada(lineas) or fecha.strftime("%d/%m/%Y")
            return fecha, fecha_publicada, valores, cabezas, url_para_fecha(fecha)

    raise RuntimeError("No se encontró una rueda MAG con los cinco promedios y las cabezas totales en los últimos 10 días")


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
    fecha, fecha_publicada, valores, cabezas, url = obtener_ultima_rueda()
    anterior = cargar_anterior()
    fecha_anterior = anterior.get("date")

    # Si no apareció una rueda nueva, conservar todo lo anterior.
    if fecha_publicada and fecha_anterior and fecha_publicada == fecha_anterior:
        print(f"MAG: sin rueda nueva ({fecha_publicada}). Se conservan mag.json y mag_previous.json.")
        return

    cambios = calcular_variaciones(valores, anterior.get("values", {}))

    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Mercado Agroganadero de Cañuelas",
        "url": url,
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
