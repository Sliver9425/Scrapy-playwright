"""
Scraper de TikTok SOLO con Playwright (sin BeautifulSoup ni requests).

Uso:  python tiktok_scraper.py usuario [cantidad_videos]
Genera <usuario>.json y <usuario>.csv

Flujo:
  1. Abre el perfil con Chrome real.
  2. Lee los datos del perfil con locators de Playwright (el <script> con el JSON).
  3. Escucha la respuesta de red que la propia pagina pide para su lista de videos
     (trae vistas, likes, comentarios y compartidos): no se entra video por video.
Si aparece un captcha, resuélvelo en el navegador y presiona Enter en la terminal.
"""
import csv
import json
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SELECTOR_JSON = "script#__UNIVERSAL_DATA_FOR_REHYDRATION__"


def pausa_captcha(mensaje):
    print(f"\n[!] {mensaje}")
    input("    Resuelve el captcha en el navegador y presiona Enter aquí para continuar... ")


def obtener_perfil(page, usuario):
    """Abre el perfil y lee el JSON embebido usando solo Playwright."""
    page.goto(f"https://www.tiktok.com/@{usuario}", wait_until="domcontentloaded")
    for intento in range(2):
        try:
            page.wait_for_selector(SELECTOR_JSON, state="attached", timeout=15000)
            break
        except PWTimeout:
            if intento == 0:
                pausa_captcha("No se encontraron los datos del perfil (posible captcha).")
                page.reload(wait_until="domcontentloaded")
            else:
                raise RuntimeError("No se pudo cargar el perfil")

    texto = page.locator(SELECTOR_JSON).inner_text()
    info = json.loads(texto)["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    stats = info["stats"]
    return {
        "usuario": info["user"]["uniqueId"],
        "seguidores": stats["followerCount"],
        "seguidos": stats["followingCount"],
        "likes_totales": stats["heartCount"],
        "videos": stats["videoCount"],
    }


def crear_escucha(capturados):
    """Guarda los videos de las respuestas de red de la lista de videos del perfil."""
    def on_response(resp):
        if "/api/post/item_list" not in resp.url or resp.status != 200:
            return
        try:
            for item in resp.json().get("itemList") or []:
                capturados[item["id"]] = item
        except Exception:
            pass
    return on_response


def esperar_videos(page, capturados, cantidad):
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

    capturados = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="perfil_navegador",
            channel="chrome",
            headless=False,
            locale="es-ES",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", crear_escucha(capturados))  # antes de abrir el perfil

        resultado = {"perfil": obtener_perfil(page, usuario), "ultimos_videos": []}

        esperar_videos(page, capturados, cantidad)
        if not capturados:
            pausa_captcha("No se recibió la lista de videos (posible captcha).")
            page.reload(wait_until="domcontentloaded")
            esperar_videos(page, capturados, cantidad)

        context.close()

    filas = [item_a_fila(it, usuario) for it in capturados.values()]
    filas.sort(key=lambda f: f["_orden"], reverse=True)
    for f in filas:
        f.pop("_orden")
    resultado["ultimos_videos"] = filas[:cantidad]
    print(f"Videos obtenidos: {len(resultado['ultimos_videos'])}")

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    with open(f"{usuario}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    guardar_csv(resultado, usuario)
    print(f"\nGuardado: {usuario}.json y {usuario}.csv")


if __name__ == "__main__":
    main()