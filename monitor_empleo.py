#!/usr/bin/env python3
"""
Monitor de Convocatorias de Empleo Público → Telegram + Panel Web
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

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "TU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TU_CHAT_ID_AQUI")

ESTADO_FILE   = Path("estado_webs.json")
HISTORIAL_FILE = Path("historial.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("monitor_empleo.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

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

MAX_LINEAS_DIFF = 10


# ── EXTRACCIÓN ─────────────────────────────────

def extraer_enlaces(soup):
    enlaces = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if any(ext in href.lower() for ext in [".pdf", ".doc", ".xls", "contenido", "convocatoria", "resolucion"]):
            enlaces.add(href)
    return "\n".join(sorted(enlaces))


def extraer_texto(soup, selector):
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


def obtener_contenido(web):
    url        = web["url"]
    timeout    = web["timeout"]
    reintentos = web["reintentos"]
    modo       = web.get("modo", "texto")
    headers    = {**HEADERS_BASE, **web.get("headers_extra", {})}
    session    = requests.Session()
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


# ── COMPARACIÓN ────────────────────────────────

def calcular_hash(texto):
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def obtener_lineas_nuevas(anterior, nuevo):
    set_anterior = set(anterior.splitlines())
    return [l for l in nuevo.splitlines() if l.strip() and l not in set_anterior]


def formatear_diff(lineas_nuevas, modo):
    if not lineas_nuevas:
        return "  (contenido reorganizado o modificado)"
    filtradas = [l for l in lineas_nuevas if len(l.strip()) > 10]
    if not filtradas:
        return "  (cambios menores en el formato)"
    mostrar = filtradas[:MAX_LINEAS_DIFF]
    resultado = ""
    for linea in mostrar:
        if modo == "enlaces":
            nombre = linea.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
            resultado += f"  ➕ {nombre[:80]}\n"
        else:
            resultado += f"  ➕ {linea[:80]}\n"
    if len(filtradas) > MAX_LINEAS_DIFF:
        resultado += f"  ... y {len(filtradas) - MAX_LINEAS_DIFF} cambios más\n"
    return resultado.rstrip()


# ── ESTADO Y HISTORIAL ─────────────────────────

def cargar_estado():
    if ESTADO_FILE.exists():
        try:
            with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error cargando estado: {e}")
    return {}


def guardar_estado(estado):
    with open(ESTADO_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def cargar_historial():
    if HISTORIAL_FILE.exists():
        try:
            with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"webs": [], "historial": [], "ultima_comprobacion": None}


def guardar_historial(datos):
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ── TELEGRAM ───────────────────────────────────

def enviar_telegram(mensaje):
    if TELEGRAM_TOKEN == "TU_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        log.warning("⚠️  Telegram no configurado.")
        print(f"\n📨 MENSAJE:\n{mensaje}\n")
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


# ── MONITOR PRINCIPAL ──────────────────────────

def monitorizar():
    log.info("=" * 60)
    log.info(f"Comprobación iniciada: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 60)

    ahora           = datetime.now().isoformat()
    estado_anterior = cargar_estado()
    historial_datos = cargar_historial()
    estado_nuevo    = {}
    cambios         = []
    webs_panel      = []

    for web in WEBS:
        log.info(f"\n🔍 Comprobando: {web['nombre']}")
        contenido_nuevo = obtener_contenido(web)

        # Buscar último cambio de esta web en el historial
        ultimo_cambio = next(
            (ev["fecha"] for ev in reversed(historial_datos.get("historial", []))
             if ev["web"] == web["nombre"]), None
        )

        if contenido_nuevo is None:
            log.warning(f"  ⚠️  Sin acceso a {web['nombre']}, omitiendo")
            if web["nombre"] in estado_anterior:
                estado_nuevo[web["nombre"]] = estado_anterior[web["nombre"]]
            webs_panel.append({
                "nombre": web["nombre"],
                "url": web["url"],
                "estado": "error",
                "ultima_comprobacion": ahora,
                "ultimo_cambio": ultimo_cambio,
            })
            continue

        hash_nuevo = calcular_hash(contenido_nuevo)
        estado_nuevo[web["nombre"]] = {
            "hash": hash_nuevo,
            "contenido": contenido_nuevo,
            "ultima_comprobacion": ahora,
            "url": web["url"],
        }

        if web["nombre"] not in estado_anterior:
            log.info(f"  📋 Primera comprobación registrada para {web['nombre']}")
        elif estado_anterior[web["nombre"]]["hash"] != hash_nuevo:
            log.info(f"  🚨 CAMBIO DETECTADO en {web['nombre']}")
            contenido_anterior = estado_anterior[web["nombre"]].get("contenido", "")
            lineas_nuevas = obtener_lineas_nuevas(contenido_anterior, contenido_nuevo)
            cambios.append((web, lineas_nuevas))
            ultimo_cambio = ahora
        else:
            log.info(f"  ✅ Sin cambios en {web['nombre']}")

        webs_panel.append({
            "nombre": web["nombre"],
            "url": web["url"],
            "estado": "ok",
            "ultima_comprobacion": ahora,
            "ultimo_cambio": ultimo_cambio,
        })

    guardar_estado(estado_nuevo)

    # Actualizar historial para el panel web
    for web, lineas_nuevas in cambios:
        filtradas = [l for l in lineas_nuevas if len(l.strip()) > 10]
        historial_datos["historial"].append({
            "fecha": ahora,
            "web": web["nombre"],
            "url": web["url"],
            "cambios": filtradas[:20],
        })
    # Mantener solo los últimos 100 eventos
    historial_datos["historial"] = historial_datos["historial"][-100:]
    historial_datos["webs"] = webs_panel
    historial_datos["ultima_comprobacion"] = ahora
    guardar_historial(historial_datos)

    # Notificación Telegram si hay cambios
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
            + f"\n\n📊 <a href='https://m8793.github.io/MONITOREO-WEB/'>Ver panel completo</a>"
        )
        if len(mensaje) > 4000:
            mensaje = mensaje[:3950] + "\n\n... (ver panel para más detalles)"
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
            "✅ Configuración correcta. Recibirás notificaciones cuando haya cambios en:\n\n"
            "• Justicia Canarias – Procesos Selectivos\n"
            "• Cabildo de La Palma – Empleo Público\n"
            "• SCS – Listas de Empleo\n"
            "• SEPE – Funcionarios Interinos\n\n"
            f"📊 Panel: https://m8793.github.io/MONITOREO-WEB/\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        enviar_telegram(mensaje)
    else:
        monitorizar()
