"""
Scraper HIBRIDO de TikTok: Playwright (carga la pagina y escucha respuestas)
+ BeautifulSoup (analiza el HTML renderizado).

Uso:  python tiktok_scraper_hibrido.py usuario [cantidad_videos]
Genera <usuario>_hibrido.json y <usuario>_hibrido.csv

Flujo:
  1. Playwright abre el perfil con Chrome real y escucha la respuesta de red que la
     propia pagina pide para llenar su cuadricula de videos (incluye las estadisticas).
  2. BeautifulSoup lee del HTML renderizado los datos del perfil (seguidores, seguidos).
  3. No se entra video por video: asi se evita el error 403 de las paginas de video.
Si aparece un captcha, resuélvelo en el navegador y presiona Enter en la terminal.
"""
import csv
import json
import sys
import time
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ID_JSON = "__UNIVERSAL_DATA_FOR_REHYDRATION__"


def pausa_captcha(mensaje):
    print(f"\n[!] {mensaje}")
    input("    Resuelve el captcha en el navegador y presiona Enter aquí para continuar... ")


def cargar_perfil(page, usuario):
    """Abre el perfil y devuelve su HTML renderizado. Pausa si hay captcha."""
    page.goto(f"https://www.tiktok.com/@{usuario}", wait_until="domcontentloaded")
    for intento in range(2):
        try:
            page.wait_for_selector(f"script#{ID_JSON}", state="attached", timeout=15000)
            break
        except PWTimeout:
            if intento == 0:
                pausa_captcha("No se encontraron los datos del perfil (posible captcha).")
                page.reload(wait_until="domcontentloaded")
    html = page.content()
    if BeautifulSoup(html, "html.parser").find("script", id=ID_JSON) is None:
        raise RuntimeError("La página no contiene los datos del perfil")
    return html


def obtener_perfil(html):
    """BeautifulSoup busca el <script> con los datos y de ahi se saca el perfil."""
    tag = BeautifulSoup(html, "html.parser").find("script", id=ID_JSON)
    info = json.loads(tag.string)["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    stats = info["stats"]
    return {
        "usuario": info["user"]["uniqueId"],
        "seguidores": stats["followerCount"],
        "seguidos": stats["followingCount"],
        "likes_totales": stats["heartCount"],
        "videos": stats["videoCount"],
    }


def crear_escucha(capturados):
    """Devuelve una funcion que guarda los videos de las respuestas de la lista de videos."""
    def on_response(resp):
        if "/api/post/item_list" not in resp.url or resp.status != 200:
            return
        try:
            for item in resp.json().get("itemList") or []:
                capturados[item["id"]] = item
        except Exception:
            pass  # respuesta vacia o no JSON: se ignora
    return on_response


def esperar_videos(page, capturados, cantidad):
    """Espera/scrollea hasta tener suficientes videos capturados."""
    for _ in range(8):
        if len(capturados) >= cantidad:
            return
        page.mouse.wheel(0, 3000)
        time.sleep(2.5)


def item_a_fila(item, usuario):
    s = item.get("stats", {})
    fecha = ""
    if item.get("createTime"):
        fecha = datetime.fromtimestamp(int(item["createTime"])).strftime("%Y-%m-%d %H:%M")
    return {
        "url": f"https://www.tiktok.com/@{usuario}/video/{item['id']}",
        "fecha": fecha,
        "descripcion": item.get("desc", ""),
        "vistas": s.get("playCount"),
        "likes": s.get("diggCount"),
        "comentarios": s.get("commentCount"),
        "compartidos": s.get("shareCount"),
        "_orden": int(item.get("createTime") or 0),
    }


def guardar_csv(resultado, nombre_archivo):
    perfil = resultado["perfil"]
    columnas = ["usuario", "seguidores", "seguidos", "url", "fecha", "descripcion",
                "vistas", "likes", "comentarios", "compartidos"]
    base = {"usuario": perfil["usuario"], "seguidores": perfil["seguidores"],
            "seguidos": perfil["seguidos"]}
    filas = [{**base, **v} for v in resultado["ultimos_videos"]] or [base]
    with open(f"{nombre_archivo}.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(filas)


def main():
    if len(sys.argv) >= 2:
        usuario = sys.argv[1].lstrip("@")
    else:
        usuario = input("Usuario de TikTok a analizar (ej. @khaby.lame): ").strip().lstrip("@")
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    capturados = {}  # id_video -> datos del video

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="perfil_navegador",
            channel="chrome",  # Google Chrome real instalado en la PC
            headless=False,
            locale="es-ES",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", crear_escucha(capturados))  # antes de abrir el perfil

        html = cargar_perfil(page, usuario)
        resultado = {"perfil": obtener_perfil(html), "ultimos_videos": []}

        esperar_videos(page, capturados, cantidad)
        if not capturados:
            pausa_captcha("No se recibió la lista de videos (posible captcha).")
            page.reload(wait_until="domcontentloaded")
            esperar_videos(page, capturados, cantidad)

        context.close()

    filas = [item_a_fila(it, usuario) for it in capturados.values()]
    filas.sort(key=lambda f: f["_orden"], reverse=True)  # mas recientes primero (ignora fijados)
    for f in filas:
        f.pop("_orden")
    resultado["ultimos_videos"] = filas[:cantidad]
    print(f"Videos obtenidos: {len(resultado['ultimos_videos'])}")

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    nombre = f"{usuario}_hibrido"
    with open(f"{nombre}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    guardar_csv(resultado, nombre)
    print(f"\nGuardado: {nombre}.json y {nombre}.csv")


if __name__ == "__main__":
    main()