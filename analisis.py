"""
analisis.py - Analisis de videos de TikTok con modelos de Hugging Face.

Uso:  python analisis.py usuario_hibrido.json
      (el JSON lo genera tiktok_scraper_hibrido.py; ejecútalo con 10 videos)

Pipeline por video:
  1. yt-dlp descarga el audio            -> audios/<id>.wav
  2. Whisper (HF) transcribe en español  -> transcripciones.json (cache)
  3. Texto del creador = descripcion + transcripcion
  4. Sentimiento y emociones (pysentimiento/robertuito, en español)
  5. Traduccion es->en (Helsinki-NLP/opus-mt-es-en) y Big Five (Minej/bert-base-personality)
Salida: analisis_<usuario>.csv  (una fila por video + fila PROMEDIO)

Si yt-dlp no logra descargar un video, copia el archivo a mano a la carpeta audios/
con el nombre <id_del_video>.mp4 (o .mp3/.wav) y vuelve a ejecutar.
"""
import csv
import glob
import json
import os
import sys
from statistics import mean

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # aviso inofensivo en Windows

import torch
from pysentimiento import create_analyzer
from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer, BertForSequenceClassification,
                          BertTokenizer, pipeline)
from yt_dlp import YoutubeDL

CARPETA_AUDIOS = "audios"
ARCHIVO_TRANSCRIPCIONES = "transcripciones.json"
MODELO_WHISPER = "openai/whisper-small"          # en CPU: "openai/whisper-base" es mas rapido
MODELO_TRADUCCION = "Helsinki-NLP/opus-mt-es-en"
MODELO_BIGFIVE = "Minej/bert-base-personality"
# Orden de salida segun la tarjeta del modelo (verifícalo en huggingface.co/Minej/bert-base-personality)
RASGOS = ["Extroversion", "Neuroticism", "Agreeableness", "Conscientiousness", "Openness"]
MIN_PALABRAS = 5


def id_video(url):
    return url.rstrip("/").split("/")[-1].split("?")[0]


def dividir(texto, max_palabras):
    palabras = texto.split()
    return [" ".join(palabras[i:i + max_palabras]) for i in range(0, len(palabras), max_palabras)]


# ---------- 1. Descarga de audio ----------
def buscar_audio(vid):
    archivos = glob.glob(os.path.join(CARPETA_AUDIOS, f"{vid}.*"))
    return archivos[0] if archivos else None


def descargar_audio(url, vid):
    os.makedirs(CARPETA_AUDIOS, exist_ok=True)
    if buscar_audio(vid):
        return buscar_audio(vid)
    opciones = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(CARPETA_AUDIOS, f"{vid}.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    }
    try:
        with YoutubeDL(opciones) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"   No se pudo descargar ({str(e)[:80]}...)")
    return buscar_audio(vid)


# ---------- 2. Transcripcion ----------
def cargar_cache():
    if os.path.exists(ARCHIVO_TRANSCRIPCIONES):
        with open(ARCHIVO_TRANSCRIPCIONES, encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_cache(cache):
    with open(ARCHIVO_TRANSCRIPCIONES, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ---------- 3-5. Analisis de texto ----------
def traducir(tok_tr, mod_tr, texto):
    """Traduce es->en usando el modelo directamente (el pipeline 'translation' ya no existe en transformers v5)."""
    traducidas = []
    for parte in dividir(texto, 60):
        entradas = tok_tr(parte, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            salida = mod_tr.generate(**entradas, max_new_tokens=256)
        traducidas.append(tok_tr.decode(salida[0], skip_special_tokens=True))
    return " ".join(traducidas)


def calcular_bigfive(tokenizador, modelo, texto_en):
    predicciones = []
    for parte in dividir(texto_en, 200):
        entradas = tokenizador(parte, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            salida = modelo(**entradas).logits.squeeze().tolist()
        predicciones.append(salida)
    return {r: round(mean(p[i] for p in predicciones), 4) for i, r in enumerate(RASGOS)}


def calcular_probas(analizador, texto, prefijo):
    resultados = analizador.predict(dividir(texto, 60))
    if not isinstance(resultados, list):
        resultados = [resultados]
    acumulado = {}
    for r in resultados:
        for clave, valor in r.probas.items():
            acumulado.setdefault(clave, []).append(valor)
    return {f"{prefijo}_{k}": round(mean(v), 4) for k, v in acumulado.items()}


def main():
    if len(sys.argv) < 2:
        print("Uso: python analisis.py usuario_hibrido.json")
        sys.exit(1)
    ruta_json = sys.argv[1]
    with open(ruta_json, encoding="utf-8") as f:
        datos = json.load(f)
    usuario = datos["perfil"]["usuario"]
    videos = datos["ultimos_videos"]
    print(f"Analizando {len(videos)} videos de @{usuario}")

    print("\nCargando modelos (la primera vez se descargan, puede tardar)...")
    asr = pipeline("automatic-speech-recognition", model=MODELO_WHISPER, chunk_length_s=30)
    tok_tr = AutoTokenizer.from_pretrained(MODELO_TRADUCCION)
    mod_tr = AutoModelForSeq2SeqLM.from_pretrained(MODELO_TRADUCCION)
    tok_bf = BertTokenizer.from_pretrained(MODELO_BIGFIVE)
    mod_bf = BertForSequenceClassification.from_pretrained(MODELO_BIGFIVE)
    sentimiento = create_analyzer(task="sentiment", lang="es")
    emocion = create_analyzer(task="emotion", lang="es")

    cache = cargar_cache()
    filas = []

    for i, v in enumerate(videos, 1):
        vid = id_video(v["url"])
        print(f"\n[{i}/{len(videos)}] {v['url']}")

        # Audio y transcripcion
        transcripcion = cache.get(vid, "")
        if not transcripcion:
            archivo = descargar_audio(v["url"], vid)
            if archivo:
                print("   Transcribiendo con Whisper...")
                transcripcion = asr(archivo, generate_kwargs={"language": "spanish", "task": "transcribe"})["text"].strip()
                cache[vid] = transcripcion
                guardar_cache(cache)
            else:
                print("   Sin audio: se usará solo la descripción")

        texto = f"{v.get('descripcion', '')} {transcripcion}".strip()
        fila = {
            "video": vid,
            "url": v["url"],
            "fuente": "descripcion+audio" if transcripcion else "solo descripcion",
            "palabras": len(texto.split()),
        }

        if len(texto.split()) < MIN_PALABRAS:
            print("   Texto insuficiente para analizar")
            filas.append(fila)
            continue

        print("   Analizando sentimiento, emociones y Big Five...")
        fila.update(calcular_probas(sentimiento, texto, "sent"))
        fila.update(calcular_probas(emocion, texto, "emo"))
        fila.update(calcular_bigfive(tok_bf, mod_bf, traducir(tok_tr, mod_tr, texto)))
        filas.append(fila)

    # Fila de promedios (solo sobre videos analizados)
    columnas = []
    for f in filas:
        for k in f:
            if k not in columnas:
                columnas.append(k)
    numericas = [c for c in columnas if c.startswith(("sent_", "emo_")) or c in RASGOS]
    promedio = {"video": "PROMEDIO", "url": "", "fuente": "", "palabras": sum(f["palabras"] for f in filas)}
    for c in numericas:
        valores = [f[c] for f in filas if c in f]
        if valores:
            promedio[c] = round(mean(valores), 4)
    filas.append(promedio)

    salida = f"analisis_{usuario}.csv"
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    print("\n=== Promedio Big Five (estimación exploratoria) ===")
    for r in RASGOS:
        if r in promedio:
            print(f"  {r:<18} {promedio[r]}")
    print(f"\nGuardado: {salida}")
    print("Nota: estimación basada en texto; no es una evaluación psicológica.")


if __name__ == "__main__":
    main()