"""
Scraper de perfil publico de TikTok (proyecto de clase).
Uso:  python tiktok_scraper.py @usuario [cantidad_videos]
      (si no pasas el usuario, el programa te lo pregunta)
Genera <usuario>.json y <usuario>.csv

Si TikTok muestra un captcha, el programa se pausa: resuélvelo en la
ventana del navegador y presiona Enter en la terminal para continuar.
"""
import csv
import json
import sys
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SELECTOR_JSON = "script#__UNIVERSAL_DATA_FOR_REHYDRATION__"


def pausa_captcha(mensaje):
    print(f"\n[!] {mensaje}")
    input("    Resuelve el captcha en el navegador y presiona Enter aquí para continuar... ")


def extraer_json_embebido(page):
    """TikTok guarda los datos de la pagina en un <script> con este id.
    Si no aparece (captcha), pide ayuda manual y reintenta una vez."""
    for intento in range(2):
        try:
            page.wait_for_selector(SELECTOR_JSON, state="attached", timeout=15000)
            texto = page.locator(SELECTOR_JSON).inner_text()
            return json.loads(texto)["__DEFAULT_SCOPE__"]
        except PWTimeout:
            if intento == 0:
                pausa_captcha("No se encontraron los datos de la página (posible captcha).")
                page.reload(wait_until="domcontentloaded")
    raise RuntimeError("No se pudo obtener el JSON de la página")


def obtener_perfil(page, usuario):
    page.goto(f"https://www.tiktok.com/@{usuario}", wait_until="domcontentloaded")
    data = extraer_json_embebido(page)
    info = data["webapp.user-detail"]["userInfo"]
    stats = info["stats"]
    return {
        "usuario": info["user"]["uniqueId"],
        "seguidores": stats["followerCount"],
        "seguidos": stats["followingCount"],
        "likes_totales": stats["heartCount"],
        "videos": stats["videoCount"],
    }


def leer_links(page):
    links = page.eval_on_selector_all('a[href*="/video/"]', "els => els.map(e => e.href)")
    return list(dict.fromkeys(links))  # sin duplicados, conserva orden


def obtener_links_videos(page, cantidad):
    """Espera los videos del perfil; si no aparecen (captcha), pausa para resolverlo."""
    try:
        page.wait_for_selector('a[href*="/video/"]', timeout=10000)
    except PWTimeout:
        pausa_captcha("No aparecen los videos del perfil (posible captcha).")
        try:
            page.wait_for_selector('a[href*="/video/"]', timeout=15000)
        except PWTimeout:
            print("Sigue sin haber videos visibles; revisa si el perfil es público.")
            return []

    links = leer_links(page)
    for _ in range(5):
        if len(links) >= cantidad:
            break
        page.mouse.wheel(0, 3000)
        time.sleep(2)
        links = leer_links(page)
    return links[:cantidad]


def obtener_video(page, url):
    page.goto(url, wait_until="domcontentloaded")
    data = extraer_json_embebido(page)
    item = data["webapp.video-detail"]["itemInfo"]["itemStruct"]
    s = item["stats"]
    return {
        "url": url,
        "descripcion": item.get("desc", ""),
        "vistas": s.get("playCount"),
        "likes": s.get("diggCount"),
        "comentarios": s.get("commentCount"),
        "compartidos": s.get("shareCount"),
    }


def guardar_csv(resultado, usuario):
    """Una fila por video, con los datos del perfil repetidos en cada fila.
    Si no hubo videos, guarda igual una fila con solo el perfil."""
    perfil = resultado["perfil"]
    columnas = ["usuario", "seguidores", "seguidos", "url", "descripcion",
                "vistas", "likes", "comentarios", "compartidos"]
    base = {"usuario": perfil["usuario"], "seguidores": perfil["seguidores"],
            "seguidos": perfil["seguidos"]}
    filas = [{**base, **v} for v in resultado["ultimos_videos"]] or [base]
    with open(f"{usuario}.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(filas)


def main():
    if len(sys.argv) >= 2:
        usuario = sys.argv[1].lstrip("@")
    else:
        usuario = input("Usuario de TikTok a analizar (ej. @khaby.lame): ").strip().lstrip("@")
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    with sync_playwright() as p:
        # Contexto persistente: guarda cookies en la carpeta "perfil_navegador",
        # así el captcha resuelto se recuerda en la siguiente ejecución.
        context = p.chromium.launch_persistent_context(
            user_data_dir="perfil_navegador",
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            locale="es-ES",
        )
        page = context.pages[0] if context.pages else context.new_page()

        resultado = {"perfil": obtener_perfil(page, usuario), "ultimos_videos": []}

        # Los links se obtienen UNA vez, estando en la página del perfil
        links = obtener_links_videos(page, cantidad)
        print(f"Videos encontrados: {len(links)}")

        for url in links:
            try:
                resultado["ultimos_videos"].append(obtener_video(page, url))
            except Exception as e:
                print(f"No se pudo leer {url}: {e}")
            time.sleep(2)

        context.close()

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    with open(f"{usuario}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    guardar_csv(resultado, usuario)
    print(f"\nGuardado: {usuario}.json y {usuario}.csv")


if __name__ == "__main__":
    main()