#!/usr/bin/env python3
"""
Monitor de Convocatorias de Empleo Público → Telegram
======================================================
Monitoriza varias webs y envía notificación por Telegram
cuando detecta cambios en el contenido, indicando exactamente qué cambió.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "TU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TU_CHAT_ID_AQUI")
# ──────────────────────────────────────────────

ESTADO_FILE = Path("estado_webs.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("monitor_empleo.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# WEBS A MONITORIZAR
# ──────────────────────────────────────────────
WEBS = [
    {
        "nombre": "Justicia Canarias – Procesos Selectivos",
        "url": "https://www.gobiernodecanarias.org/justicia/RecursosHumanos/ProcesosSelectivos/",
        "modo": "texto",
        "selector": "body",
        "timeout": 30,
        "reintentos": 3,
        "headers_extra": {},
    },
    {
        "nombre": "Cabildo de La Palma – Empleo Público",
        "url": "https://sedeelectronica.cabildodelapalma.es/sta/CarpetaPublic/doEvent?APP_CODE=STA&PAGE_CODE=PTS2_EMPLEO",
        "modo": "texto",
        "selector": "body",
        "timeout": 45,
        "reintentos": 5,
        "headers_extra": {},
    },
    {
        "nombre": "SCS – Listas de Empleo y Supletorias",
        "url": "https://www3.gobiernodecanarias.org/sanidad/scs/contenidoGenerico.jsp?idDocument=b66c1847-b3d7-11eb-9269-832e239ed123&idCarpeta=61e907e3-d473-11e9-9a19-e5198e027117",
        "modo": "texto",
        "selector": "#centercontainer",
        "timeout": 30,
        "reintentos": 3,
        "headers_extra": {},
    },
    {
        "nombre": "SEPE – Funcionarios Interinos",
        "url": "https://www.sepe.es/HomeSepe/que-es-el-sepe/convocatorias/funcionarios-interinos.html",
        "modo": "enlaces",
        "selector": "body",
        "timeout": 60,
        "reintentos": 4,
        "headers_extra": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
            ),
            "Sec-Ch-Ua": '"Microsoft Edge";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Referer": "https://www.google.es/",
            "DNT": "1",
        },
    },
]

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Máximo de líneas nuevas a mostrar en el mensaje de Telegram
MAX_LINEAS_DIFF = 10


# ──────────────────────────────────────────────
# EXTRACCIÓN DE CONTENIDO
# ──────────────────────────────────────────────

def extraer_enlaces(soup: BeautifulSoup) -> str:
    """Extrae enlaces a documentos ordenados alfabéticamente."""
    enlaces = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if any(ext in href.lower() for ext in [".pdf", ".doc", ".xls", "contenido", "convocatoria", "resolucion"]):
            enlaces.add(href)
    return "\n".join(sorted(enlaces))


def extraer_texto(soup: BeautifulSoup, selector: str) -> str:
    """Extrae el texto limpio del selector indicado."""
    for sel in selector.split(","):
        sel = sel.strip()
        elemento = soup.select_one(sel)
        if elemento:
            texto = elemento.get_text(separator="\n")
            lineas = [l.strip() for l in texto.splitlines() if l.strip()]
            return "\n".join(lineas)
    texto = soup.body.get_text(separator="\n") if soup.body else ""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    return "\n".join(lineas)


def obtener_contenido(web: dict) -> str | None:
    """Descarga la página y extrae el contenido según el modo configurado."""
    url        = web["url"]
    timeout    = web["timeout"]
    reintentos = web["reintentos"]
    modo       = web.get("modo", "texto")

    headers = {**HEADERS_BASE, **web.get("headers_extra", {})}
    session = requests.Session()
    session.headers.update(headers)

    for intento in range(1, reintentos + 1):
        try:
            log.info(f"  Descargando: {web['nombre']} (intento {intento}/{reintentos})")

            if "sepe.es" in url and intento == 1:
                try:
                    session.get("https://www.sepe.es/HomeSepe/", timeout=20)
                    time.sleep(2)
                except Exception:
                    pass

            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            if modo == "enlaces":
                contenido = extraer_enlaces(soup)
                if contenido:
                    log.info(f"  Modo enlaces: {len(contenido.splitlines())} enlaces encontrados")
                    return contenido
                else:
                    return extraer_texto(soup, web["selector"])
            else:
                return extraer_texto(soup, web["selector"])

        except requests.exceptions.Timeout:
            log.warning(f"  Timeout en intento {intento} para {web['nombre']}")
            if intento < reintentos:
                time.sleep(10 * intento)
        except requests.exceptions.RequestException as e:
            log.error(f"  Error en {web['nombre']}: {e}")
            if intento < reintentos:
                time.sleep(5)

    log.error(f"  No se pudo acceder a {web['nombre']} tras {reintentos} intentos")
    return None


# ──────────────────────────────────────────────
# COMPARACIÓN DE CAMBIOS
# ──────────────────────────────────────────────

def calcular_hash(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def obtener_lineas_nuevas(texto_anterior: str, texto_nuevo: str) -> list[str]:
    """Devuelve las líneas que están en el texto nuevo pero no en el anterior."""
    lineas_anteriores = set(texto_anterior.splitlines())
    lineas_nuevas = [
        l for l in texto_nuevo.splitlines()
        if l.strip() and l not in lineas_anteriores
    ]
    return lineas_nuevas


def formatear_diff(lineas_nuevas: list[str], modo: str) -> str:
    """Formatea las líneas nuevas para mostrar en Telegram."""
    if not lineas_nuevas:
        return "  (contenido reorganizado o modificado)"

    # Filtrar líneas muy cortas o irrelevantes
    lineas_filtradas = [
        l for l in lineas_nuevas
        if len(l.strip()) > 10
    ]

    if not lineas_filtradas:
        return "  (cambios menores en el formato)"

    # Limitar el número de líneas
    mostrar = lineas_filtradas[:MAX_LINEAS_DIFF]
    resultado = ""

    for linea in mostrar:
        # Para enlaces, extraer solo el nombre del archivo
        if modo == "enlaces":
            nombre = linea.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
            resultado += f"  ➕ {nombre[:80]}\n"
        else:
            resultado += f"  ➕ {linea[:80]}\n"

    if len(lineas_filtradas) > MAX_LINEAS_DIFF:
        resultado += f"  ... y {len(lineas_filtradas) - MAX_LINEAS_DIFF} cambios más\n"

    return resultado.rstrip()


# ──────────────────────────────────────────────
# ESTADO
# ──────────────────────────────────────────────

def cargar_estado() -> dict:
    if ESTADO_FILE.exists():
        try:
            with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error cargando estado: {e}")
    return {}


def guardar_estado(estado: dict):
    with open(ESTADO_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────

def enviar_telegram(mensaje: str):
    if TELEGRAM_TOKEN == "TU_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        log.warning("⚠️  Telegram no configurado.")
        print(f"\n📨 MENSAJE QUE SE ENVIARÍA:\n{mensaje}\n")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("  ✅ Notificación enviada a Telegram")
    except Exception as e:
        log.error(f"  ❌ Error enviando a Telegram: {e}")


# ──────────────────────────────────────────────
# MONITOR PRINCIPAL
# ──────────────────────────────────────────────

def monitorizar():
    log.info("=" * 60)
    log.info(f"Comprobación iniciada: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 60)

    estado_anterior = cargar_estado()
    estado_nuevo    = {}
    cambios         = []  # Lista de (web, lineas_nuevas)

    for web in WEBS:
        log.info(f"\n🔍 Comprobando: {web['nombre']}")
        contenido_nuevo = obtener_contenido(web)

        if contenido_nuevo is None:
            log.warning(f"  ⚠️  Sin acceso a {web['nombre']}, omitiendo")
            if web["nombre"] in estado_anterior:
                estado_nuevo[web["nombre"]] = estado_anterior[web["nombre"]]
            continue

        hash_nuevo = calcular_hash(contenido_nuevo)
        estado_nuevo[web["nombre"]] = {
            "hash": hash_nuevo,
            "contenido": contenido_nuevo,
            "ultima_comprobacion": datetime.now().isoformat(),
            "url": web["url"],
        }

        if web["nombre"] not in estado_anterior:
            log.info(f"  📋 Primera comprobación registrada para {web['nombre']}")
        elif estado_anterior[web["nombre"]]["hash"] != hash_nuevo:
            log.info(f"  🚨 CAMBIO DETECTADO en {web['nombre']}")
            # Calcular qué cambió exactamente
            contenido_anterior = estado_anterior[web["nombre"]].get("contenido", "")
            lineas_nuevas = obtener_lineas_nuevas(contenido_anterior, contenido_nuevo)
            cambios.append((web, lineas_nuevas))
        else:
            log.info(f"  ✅ Sin cambios en {web['nombre']}")

    guardar_estado(estado_nuevo)

    if cambios:
        fecha = datetime.now().strftime("%d/%m/%Y a las %H:%M")
        bloques = []

        for web, lineas_nuevas in cambios:
            diff_texto = formatear_diff(lineas_nuevas, web.get("modo", "texto"))
            bloque = (
                f"📌 <b>{web['nombre']}</b>\n"
                f"{diff_texto}\n"
                f"🔗 <a href='{web['url']}'>Ver página</a>"
            )
            bloques.append(bloque)

        mensaje = (
            f"🚨 <b>CAMBIOS EN CONVOCATORIAS DE EMPLEO PÚBLICO</b>\n"
            f"📅 {fecha}\n\n"
            + "\n\n".join(bloques)
        )

        # Telegram tiene límite de 4096 caracteres
        if len(mensaje) > 4000:
            mensaje = mensaje[:3950] + "\n\n... (mensaje recortado, ver página)"

        enviar_telegram(mensaje)
    else:
        log.info("\n✅ Ningún cambio detectado en esta comprobación.")

    log.info("\n" + "=" * 60)
    log.info("Comprobación finalizada")
    log.info("=" * 60 + "\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        mensaje = (
            "🤖 <b>Monitor de Empleo Público activo</b>\n\n"
            "✅ Configuración correcta. Recibirás notificaciones aquí cuando haya cambios en:\n\n"
            "• Justicia Canarias – Procesos Selectivos\n"
            "• Cabildo de La Palma – Empleo Público\n"
            "• SCS – Listas de Empleo\n"
            "• SEPE – Funcionarios Interinos\n\n"
            f"🕐 Hora de inicio: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        enviar_telegram(mensaje)
    else:
        monitorizar()
