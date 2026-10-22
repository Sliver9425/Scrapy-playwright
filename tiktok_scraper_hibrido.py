"""
Scraper HIBRIDO de TikTok: Playwright (navega y escucha respuestas de red)
+ BeautifulSoup (analiza el HTML renderizado del perfil).

Uso:  python tiktok_scraper_hibrido.py usuario [cantidad_videos]
Genera:
  <usuario>_hibrido.json                 perfil + videos + primeros comentarios
  <usuario>_hibrido.csv                  una fila por video
  <usuario>_hibrido_comentarios.csv      una fila por comentario

Flujo:
  1. Abre el perfil con Chrome real y captura la lista de videos con estadisticas.
  2. BeautifulSoup lee del HTML renderizado los datos del perfil.
  3. Para cada video: hace CLIC en el desde el perfil (no abre la URL directa, que da 403)
     y captura la respuesta de red de los comentarios.
Si aparece un captcha, resuélvelo en el navegador y presiona Enter en la terminal.
"""
import csv
import json
import sys
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ID_JSON = "__UNIVERSAL_DATA_FOR_REHYDRATION__"
NUM_COMENTARIOS = 5
INCLUIR_AUTOR = False  # False = no guarda nombres de usuario de quienes comentan (privacidad)


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
    # El <script> puede aparecer en el DOM antes de recibir TODO su contenido
    # (JSON cortado). Se espera a que la página cargue y se reintenta hasta que el JSON esté completo.
    try:
        page.wait_for_load_state("load", timeout=20000)
    except PWTimeout:
        pass
    for _ in range(15):
        html = page.content()
        tag = BeautifulSoup(html, "html.parser").find("script", id=ID_JSON)
        if tag is not None and tag.string:
            try:
                json.loads(tag.string)
                return html
            except json.JSONDecodeError:
                pass
        time.sleep(1)
    raise RuntimeError("No se pudo leer el JSON completo del perfil")


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


def crear_escucha(capturados, comentarios):
    """Guarda videos (item_list) y comentarios (comment/list) de las respuestas de red."""
    def on_response(resp):
        if resp.status != 200:
            return
        try:
            if "/api/post/item_list" in resp.url:
                for item in resp.json().get("itemList") or []:
                    capturados[item["id"]] = item
            elif "/api/comment/list" in resp.url:
                vid = parse_qs(urlparse(resp.url).query).get("aweme_id", [None])[0]
                lista = resp.json().get("comments") or []
                if vid and lista and vid not in comentarios:
                    comentarios[vid] = lista
        except Exception:
            pass
    return on_response


def esperar_videos(page, capturados, cantidad):
    for _ in range(8):
        if len(capturados) >= cantidad:
            return
        page.mouse.wheel(0, 3000)
        time.sleep(2.5)


def abrir_video_con_clic(page, vid):
    """Busca el enlace del video en la cuadrícula del perfil (con scroll) y le hace clic."""
    for _ in range(6):
        enlace = page.locator(f'a[href*="/video/{vid}"]')
        if enlace.count():
            enlace.first.scroll_into_view_if_needed()
            enlace.first.click()
            return True
        page.mouse.wheel(0, 2500)
        time.sleep(1.5)
    return False


def esperar_comentarios(comentarios, vid, timeout=12):
    for _ in range(timeout * 2):
        if vid in comentarios:
            return True
        time.sleep(0.5)
    return False


def volver_al_perfil(page):
    page.go_back(wait_until="domcontentloaded")
    try:
        page.wait_for_selector('a[href*="/video/"]', timeout=10000)
    except PWTimeout:
        pass
    time.sleep(2)


def formatear_comentarios(lista):
    salida = []
    for c in lista[:NUM_COMENTARIOS]:
        fila = {
            "texto": c.get("text", ""),
            "likes": c.get("digg_count"),
            "fecha": "",
        }
        if c.get("create_time"):
            fila["fecha"] = datetime.fromtimestamp(int(c["create_time"])).strftime("%Y-%m-%d %H:%M")
        if INCLUIR_AUTOR:
            fila["autor"] = (c.get("user") or {}).get("unique_id", "")
        salida.append(fila)
    return salida


def item_a_fila(item, usuario):
    s = item.get("stats", {})
    fecha = ""
    if item.get("createTime"):
        fecha = datetime.fromtimestamp(int(item["createTime"])).strftime("%Y-%m-%d %H:%M")
    return {
        "id": item["id"],
        "url": f"https://www.tiktok.com/@{usuario}/video/{item['id']}",
        "fecha": fecha,
        "descripcion": item.get("desc", ""),
        "vistas": s.get("playCount"),
        "likes": s.get("diggCount"),
        "comentarios": s.get("commentCount"),
        "compartidos": s.get("shareCount"),
        "_orden": int(item.get("createTime") or 0),
    }


def guardar_csvs(resultado, nombre):
    perfil = resultado["perfil"]
    base = {"usuario": perfil["usuario"], "seguidores": perfil["seguidores"],
            "seguidos": perfil["seguidos"]}

    # CSV de videos (una fila por video; los primeros comentarios van unidos con " | ")
    columnas = ["usuario", "seguidores", "seguidos", "url", "fecha", "descripcion",
                "vistas", "likes", "comentarios", "compartidos", "primeros_comentarios"]
    filas = []
    for v in resultado["ultimos_videos"]:
        textos = " | ".join(c["texto"] for c in v.get("primeros_comentarios", []))
        fila = {**base, **{k: v.get(k) for k in columnas if k in v}}
        fila["primeros_comentarios"] = textos
        filas.append(fila)
    with open(f"{nombre}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas or [base])

    # CSV de comentarios (una fila por comentario)
    col_c = ["url_video", "texto", "likes", "fecha"] + (["autor"] if INCLUIR_AUTOR else [])
    with open(f"{nombre}_comentarios.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=col_c, extrasaction="ignore")
        w.writeheader()
        for v in resultado["ultimos_videos"]:
            for c in v.get("primeros_comentarios", []):
                w.writerow({"url_video": v["url"], **c})


def main():
    if len(sys.argv) >= 2:
        usuario = sys.argv[1].lstrip("@")
    else:
        usuario = input("Usuario de TikTok a analizar (ej. @khaby.lame): ").strip().lstrip("@")
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    capturados = {}   # id_video -> datos del video
    comentarios = {}  # id_video -> lista cruda de comentarios

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="perfil_navegador",
            channel="chrome",
            headless=False,
            locale="es-ES",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", crear_escucha(capturados, comentarios))

        html = cargar_perfil(page, usuario)
        resultado = {"perfil": obtener_perfil(html), "ultimos_videos": []}

        esperar_videos(page, capturados, cantidad)
        if not capturados:
            pausa_captcha("No se recibió la lista de videos (posible captcha).")
            page.reload(wait_until="domcontentloaded")
            esperar_videos(page, capturados, cantidad)

        filas = [item_a_fila(it, usuario) for it in capturados.values()]
        filas.sort(key=lambda f: f["_orden"], reverse=True)  # mas recientes primero
        filas = filas[:cantidad]
        print(f"Videos obtenidos: {len(filas)}")

        # Comentarios: se abre cada video con clic desde el perfil
        for fila in filas:
            vid = fila["id"]
            print(f"Comentarios de {fila['url']} ...")
            if abrir_video_con_clic(page, vid):
                if not esperar_comentarios(comentarios, vid):
                    print("   No llegaron comentarios (¿captcha, sin comentarios o requiere login?)")
                volver_al_perfil(page)
            else:
                print("   No se encontró el video en la cuadrícula del perfil")
            fila["primeros_comentarios"] = formatear_comentarios(comentarios.get(vid, []))
            time.sleep(2)

        context.close()

    for f in filas:
        f.pop("_orden")
        f.pop("id")
    resultado["ultimos_videos"] = filas

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    nombre = f"{usuario}_hibrido"
    with open(f"{nombre}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    guardar_csvs(resultado, nombre)
    print(f"\nGuardado: {nombre}.json, {nombre}.csv y {nombre}_comentarios.csv")


if __name__ == "__main__":
    main()