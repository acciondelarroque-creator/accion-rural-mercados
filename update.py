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

    posiciones = {}
    for fila in tabla.find_all("tr"):
        celdas = fila.find_all(["th", "td"])
        textos = [c.get_text(" ", strip=True) for c in celdas]
        if len(textos) < 7:
            continue
        posicion = textos[0]
        if not re.match(r"^[A-Z][a-z]{2}-\d{2}$", posicion):
            continue
        # Orden BCR: posición, trigo precio/variación, maíz precio/variación, soja precio/variación...
        posiciones[posicion] = {
            "trigo": (limpiar_numero(textos[1]), limpiar_numero(textos[2])),
            "maiz": (limpiar_numero(textos[3]), limpiar_numero(textos[4])),
            "soja": (limpiar_numero(textos[5]), limpiar_numero(textos[6]))
        }

    if not posiciones:
        raise RuntimeError("No se pudieron interpretar las posiciones Chicago")

    # Contratos de referencia: el siguiente contrato estándar después del mes actual.
    # En septiembre de 2026 esto produce Soja Nov-26, Maíz Dic-26 y Trigo Dic-26.
    now = datetime.now(timezone.utc)
    calendarios = {
        "soja": [1, 3, 5, 7, 8, 9, 11],
        "maiz": [3, 5, 7, 9, 12],
        "trigo": [3, 5, 7, 9, 12]
    }
    meses = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}

    referencias = {}
    for producto, calendario in calendarios.items():
        candidatos = []
        for mes in calendario:
            anio = now.year if mes > now.month else now.year + 1
            candidatos.append((anio, mes))
        anio, mes = min(candidatos)
        etiqueta = f"{meses[mes]}-{str(anio)[-2:]}"
        if etiqueta not in posiciones:
            # Si la rueda aún no tiene ese contrato, buscar el primer contrato disponible posterior al mes actual.
            disponibles = []
            for pos in posiciones:
                m = re.match(r"^[A-Z][a-z]{2}-(\d{2})$", pos)
                if not m:
                    continue
                mes_txt = pos[:3]
                mes_num = next((n for n, nombre in meses.items() if nombre == mes_txt), None)
                anio_num = 2000 + int(m.group(1))
                if mes_num is not None:
                    disponibles.append((anio_num, mes_num, pos))
            posteriores = [x for x in disponibles if (x[0] > now.year or (x[0] == now.year and x[1] > now.month))]
            if posteriores:
                posteriores.sort()
                etiqueta = posteriores[0][2]
        if etiqueta in posiciones:
            precio, variacion = posiciones[etiqueta][producto]
            referencias[producto] = {"contract": etiqueta, "value": precio, "change": variacion}
        else:
            referencias[producto] = {"contract": etiqueta, "value": None, "change": None}

    return fecha, referencias


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

    # Si la BCR no publicó una rueda nueva, conservamos la fecha y valores locales.
    # Chicago se actualiza por separado, porque puede publicarse después de la pizarra local.
    if fecha_local and fecha_anterior and fecha_local == fecha_anterior:
        datos = cargar_json(OUTPUT_FILE)
        if not datos:
            datos = {
                "updated": datetime.now(timezone.utc).isoformat(),
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
        print(json.dumps(datos, ensure_ascii=False, indent=2))
        return

    variaciones = calcular_variaciones(valores, anterior)
    datos = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Bolsa de Comercio de Rosario - Cámara Arbitral de Cereales",
        "url": LOCAL_URL,
        "date": fecha_local,
        "values": valores,
        "changes": variaciones,
        "chicago": {
            "source": "BCR - Chicago/Kansas (CME Group)",
            "url": CHICAGO_URL,
            "date": fecha_chicago,
            "values": {k: v["value"] for k, v in chicago.items()},
            "changes": {k: v["change"] for k, v in chicago.items()},
            "contracts": {k: v["contract"] for k, v in chicago.items()}
        }
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)

    with open(STATE_FILE, "w", encoding="utf-8") as archivo:
        json.dump({"values": valores, "date": fecha_local}, archivo, ensure_ascii=False, indent=2)

    print(json.dumps(datos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
