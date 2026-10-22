"""
Scraper de perfil publico de TikTok con requests + BeautifulSoup (proyecto de clase).

Uso:  python tiktok_scraper_requests.py @usuario [cantidad_videos]
      (si no pasas el usuario, el programa te lo pregunta)
Genera <usuario>_requests.json y <usuario>_requests.csv

LIMITACION: requests no ejecuta JavaScript. El perfil (seguidores, seguidos) suele
venir en el HTML, pero la lista de videos de TikTok se carga con JS, asi que puede
no aparecer. En ese caso el programa te pide pegar los links de los videos a mano.
"""
import csv
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def descargar_html(session, url):
    """Descarga una pagina y devuelve su HTML."""
    resp = session.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} al pedir {url}")
    return resp.text


def extraer_json(html):
    """Busca con BeautifulSoup el <script> con los datos y lo convierte a diccionario."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__")
    if tag is None or not tag.string:
        raise RuntimeError("No se encontraron los datos (posible captcha o bloqueo)")
    return json.loads(tag.string)["__DEFAULT_SCOPE__"]


def obtener_perfil(session, usuario):
    html = descargar_html(session, f"https://www.tiktok.com/@{usuario}")
    data = extraer_json(html)
    info = data["webapp.user-detail"]["userInfo"]
    stats = info["stats"]
    perfil = {
        "usuario": info["user"]["uniqueId"],
        "seguidores": stats["followerCount"],
        "seguidos": stats["followingCount"],
        "likes_totales": stats["heartCount"],
        "videos": stats["videoCount"],
    }
    return perfil, html


def buscar_links_videos(html, usuario, cantidad):
    """Intenta sacar links de videos del HTML (etiquetas <a> y texto crudo)."""
    soup = BeautifulSoup(html, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True) if "/video/" in a["href"]]
    ids = re.findall(rf"/@{re.escape(usuario)}/video/(\d+)", html)
    links += [f"https://www.tiktok.com/@{usuario}/video/{i}" for i in ids]
    return list(dict.fromkeys(links))[:cantidad]  # sin duplicados, conserva orden


def pedir_links_manual():
    print("\n[!] No se encontraron videos en el HTML (TikTok los carga con JavaScript).")
    texto = input("Pega links de videos separados por espacio (o Enter para omitir): ")
    return [t for t in texto.split() if "/video/" in t]


def obtener_video(session, url):
    html = descargar_html(session, url)
    data = extraer_json(html)
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


def guardar_csv(resultado, nombre_archivo):
    perfil = resultado["perfil"]
    columnas = ["usuario", "seguidores", "seguidos", "url", "descripcion",
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

    session = requests.Session()  # mantiene cookies entre peticiones

    try:
        perfil, html = obtener_perfil(session, usuario)
    except Exception as e:
        print(f"No se pudo obtener el perfil: {e}")
        sys.exit(1)

    resultado = {"perfil": perfil, "ultimos_videos": []}

    links = buscar_links_videos(html, usuario, cantidad)
    if not links:
        links = pedir_links_manual()
    print(f"Videos a procesar: {len(links)}")

    for url in links:
        try:
            resultado["ultimos_videos"].append(obtener_video(session, url))
        except Exception as e:
            print(f"No se pudo leer {url}: {e}")
        time.sleep(3)

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    nombre = f"{usuario}_requests"
    with open(f"{nombre}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    guardar_csv(resultado, nombre)
    print(f"\nGuardado: {nombre}.json y {nombre}.csv")


if __name__ == "__main__":
    main()