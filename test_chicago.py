import re
import requests
from bs4 import BeautifulSoup

SYMBOLS = {
    "soja": "https://es.tradingview.com/symbols/CBOT-ZS1!/?exchange=CBOT",
    "maiz": "https://es.tradingview.com/symbols/CBOT-ZC1!/?exchange=CBOT",
    "trigo": "https://es.tradingview.com/symbols/CBOT-ZW1!/?exchange=CBOT",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AccionRuralChicagoTest/1.0)"
}


def extraer(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # TradingView suele exponer el último precio en el HTML/estado inicial.
    patrones = [
        r'"last_price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"lastPrice"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"lp"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
    ]
    for patron in patrones:
        m = re.search(patron, html)
        if m:
            return float(m.group(1))

    # Segundo intento: buscar tablas de contratos y tomar el primer precio.
    for table in soup.find_all("table"):
        texto = table.get_text(" ", strip=True)
        if "Precio" in texto and "Vencimiento" in texto:
            filas = table.find_all("tr")
            for fila in filas[1:]:
                celdas = [c.get_text(" ", strip=True) for c in fila.find_all(["th", "td"])]
                if len(celdas) >= 3:
                    valor = celdas[2].replace("'", "").replace(",", ".")
                    m = re.search(r"\d+(?:\.\d+)?", valor)
                    if m:
                        return float(m.group(0))

    raise RuntimeError("No se encontró un precio reconocible en TradingView")


for nombre, url in SYMBOLS.items():
    precio = extraer(url)
    print(f"{nombre}: {precio}")

print("PRUEBA CHICAGO: OK")
