#!/usr/bin/env python3
"""
Monitor de Convocatorias de Empleo Público → Telegram
======================================================
Monitoriza varias webs y envía notificación por Telegram
cuando detecta cambios en el contenido.

Webs monitorizadas:
  1. Gobierno de Canarias – Justicia (Procesos Selectivos)
  2. Cabildo de La Palma – Sede Electrónica (con reintentos)
  3. SCS – Listas de empleo y supletorias
  4. SEPE – Funcionarios interinos

Uso:
  python monitor_empleo.py

Configuración:
  Edita las variables TELEGRAM_TOKEN y TELEGRAM_CHAT_ID
  con tus datos antes de ejecutar.
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
# En GitHub: se leen automáticamente de los Secrets del repositorio
# En local:  puedes escribirlos directamente aquí si lo usas en tu PC
# ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "TU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TU_CHAT_ID_AQUI")
# ──────────────────────────────────────────────

# Archivo donde se guardan los hashes anteriores
ESTADO_FILE = Path("estado_webs.json")

# Configuración de logging
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
        "selector": "body",          # Selector CSS del bloque a vigilar
        "timeout": 30,
        "reintentos": 3,
    },
    {
        "nombre": "Cabildo de La Palma – Empleo Público",
        "url": "https://sedeelectronica.cabildodelapalma.es/sta/CarpetaPublic/doEvent?APP_CODE=STA&PAGE_CODE=PTS2_EMPLEO",
        "selector": "body",
        "timeout": 45,               # Más tiempo por ser lenta
        "reintentos": 5,             # Más reintentos por los timeouts
    },
    {
        "nombre": "SCS – Listas de Empleo y Supletorias",
        "url": "https://www3.gobiernodecanarias.org/sanidad/scs/contenidoGenerico.jsp?idDocument=b66c1847-b3d7-11eb-9269-832e239ed123&idCarpeta=61e907e3-d473-11e9-9a19-e5198e027117",
        "selector": "#centercontainer",  # Bloque principal de contenido
        "timeout": 30,
        "reintentos": 3,
    },
    {
        "nombre": "SEPE – Funcionarios Interinos",
        "url": "https://www.sepe.es/HomeSepe/que-es-el-sepe/convocatorias/funcionarios-interinos.html",
        "selector": ".contenido-principal, main, #contenido, body",
        "timeout": 30,
        "reintentos": 3,
    },
]

# Headers para simular un navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ──────────────────────────────────────────────
# FUNCIONES PRINCIPALES
# ──────────────────────────────────────────────

def obtener_contenido(web: dict) -> str | None:
    """Descarga la página y extrae el texto del selector indicado."""
    url       = web["url"]
    selector  = web["selector"]
    timeout   = web["timeout"]
    reintentos = web["reintentos"]

    for intento in range(1, reintentos + 1):
        try:
            log.info(f"  Descargando: {web['nombre']} (intento {intento}/{reintentos})")
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Intentar cada selector separado por coma
            for sel in selector.split(","):
                sel = sel.strip()
                elemento = soup.select_one(sel)
                if elemento:
                    # Texto limpio: sin espacios múltiples ni líneas vacías
                    texto = elemento.get_text(separator="\n")
                    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
                    return "\n".join(lineas)

            # Si ningún selector coincide, usar todo el body
            log.warning(f"  Selector '{selector}' no encontrado, usando body completo")
            texto = soup.body.get_text(separator="\n") if soup.body else resp.text
            lineas = [l.strip() for l in texto.splitlines() if l.strip()]
            return "\n".join(lineas)

        except requests.exceptions.Timeout:
            log.warning(f"  Timeout en intento {intento} para {web['nombre']}")
            if intento < reintentos:
                time.sleep(10 * intento)  # Espera creciente entre reintentos
        except requests.exceptions.RequestException as e:
            log.error(f"  Error en {web['nombre']}: {e}")
            if intento < reintentos:
                time.sleep(5)

    log.error(f"  No se pudo acceder a {web['nombre']} tras {reintentos} intentos")
    return None


def calcular_hash(texto: str) -> str:
    """Calcula el hash MD5 del texto para detectar cambios."""
    return hashlib.md5(texto.encode("utf-8")).hexdigest()


def cargar_estado() -> dict:
    """Carga el estado anterior guardado en disco."""
    if ESTADO_FILE.exists():
        try:
            with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error cargando estado: {e}")
    return {}


def guardar_estado(estado: dict):
    """Guarda el estado actual en disco."""
    with open(ESTADO_FILE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def enviar_telegram(mensaje: str):
    """Envía un mensaje al bot de Telegram."""
    if TELEGRAM_TOKEN == "TU_TOKEN_AQUI" or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        log.warning("⚠️  Telegram no configurado. Edita TELEGRAM_TOKEN y TELEGRAM_CHAT_ID")
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


def enviar_test_telegram():
    """Envía un mensaje de prueba para verificar la configuración."""
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


def monitorizar():
    """Función principal: comprueba todas las webs y notifica cambios."""
    log.info("=" * 60)
    log.info(f"Comprobación iniciada: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 60)

    estado_anterior = cargar_estado()
    estado_nuevo    = {}
    cambios         = []

    for web in WEBS:
        log.info(f"\n🔍 Comprobando: {web['nombre']}")
        contenido = obtener_contenido(web)

        if contenido is None:
            # No se pudo acceder: mantener estado anterior si existía
            log.warning(f"  ⚠️  Sin acceso a {web['nombre']}, omitiendo")
            if web["nombre"] in estado_anterior:
                estado_nuevo[web["nombre"]] = estado_anterior[web["nombre"]]
            continue

        hash_actual = calcular_hash(contenido)
        estado_nuevo[web["nombre"]] = {
            "hash": hash_actual,
            "ultima_comprobacion": datetime.now().isoformat(),
            "url": web["url"],
        }

        if web["nombre"] not in estado_anterior:
            # Primera vez que se comprueba esta web
            log.info(f"  📋 Primera comprobación registrada para {web['nombre']}")
        elif estado_anterior[web["nombre"]]["hash"] != hash_actual:
            # ¡Hay cambios!
            log.info(f"  🚨 CAMBIO DETECTADO en {web['nombre']}")
            cambios.append(web)
        else:
            log.info(f"  ✅ Sin cambios en {web['nombre']}")

    # Guardar nuevo estado
    guardar_estado(estado_nuevo)

    # Notificar si hay cambios
    if cambios:
        fecha = datetime.now().strftime("%d/%m/%Y a las %H:%M")
        lineas_webs = "\n".join(
            f"• <b>{w['nombre']}</b>\n  🔗 <a href='{w['url']}'>Ver página</a>"
            for w in cambios
        )
        mensaje = (
            f"🚨 <b>CAMBIOS EN CONVOCATORIAS DE EMPLEO PÚBLICO</b>\n\n"
            f"📅 Detectado el {fecha}\n\n"
            f"Se han detectado cambios en:\n\n"
            f"{lineas_webs}\n\n"
            f"👆 Haz clic en los enlaces para ver las novedades."
        )
        enviar_telegram(mensaje)
    else:
        log.info("\n✅ Ningún cambio detectado en esta comprobación.")

    log.info("\n" + "=" * 60)
    log.info("Comprobación finalizada")
    log.info("=" * 60 + "\n")


# ──────────────────────────────────────────────
# PUNTO DE ENTRADA
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Enviando mensaje de prueba a Telegram...")
        enviar_test_telegram()
    else:
        monitorizar()
