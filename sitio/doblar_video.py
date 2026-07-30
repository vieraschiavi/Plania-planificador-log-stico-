"""
Plania · Doblaje del video de demostración a tres idiomas
=========================================================
Convierte el video mudo que deja `sitio/grabar_demo.py` en tres videos
narrados —español, inglés y portugués— **con la misma voz** en los tres, y
en tres pistas de subtítulos.

    python3 sitio/doblar_video.py                 # subtítulos + informe de calce
    python3 sitio/doblar_video.py --doblar        # además sintetiza el audio
    python3 sitio/doblar_video.py --doblar --ajustar   # y encoge lo que no entra

Dos cosas que conviene entender antes de tocarlo:

**Por qué la voz puede ser la misma en los tres idiomas.**
Se clona una voz a partir de una muestra de audio y después se la hace hablar
los tres idiomas. No es una voz por idioma: es la misma voz. Por eso el
doblaje conserva el timbre del video original en inglés y portugués, en vez
de sonar a tres locutores distintos.

La muestra ya está en el repo: `sitio/narracion/voz_referencia.wav`, quince
segundos sacados de la narración del video original.

Hay tres motores, y el de por defecto no necesita ni cuenta ni servidor:

  --motor local       Chatterbox Multilingual corriendo en la misma máquina.
                      Es lo que usa VoiceBox por dentro, sin la aplicación de
                      escritorio, así que sirve desde una terminal o desde CI.
                      Instalar con: pip install chatterbox-tts
  --motor voicebox    La aplicación de escritorio VoiceBox (voicebox.sh), por
                      su API local. Útil si ya se la usa para otras cosas.
  --motor elevenlabs  Servicio pago. Cobra por carácter y pide una clave.

Los dos primeros son gratis, así que re-doblar después de cambiar una línea
del guion no cuesta nada.

**Por qué se sintetiza segmento por segmento y no el guion entero.**
Si se sintetizara todo de una, el inglés y el portugués —que tardan
distinto que el español en decir lo mismo— se irían corriendo respecto de
la imagen: para el minuto uno la voz estaría hablando del copiloto mientras
en pantalla se ven las rutas. Acá cada segmento se sintetiza aparte y se
coloca en su marca de tiempo exacta, así los tres idiomas quedan pegados a
la misma imagen.

De ahí sale el control de solapamiento: si el audio real de un segmento es
más largo que su hueco, pisaría al segmento siguiente. El script lo mide y
avisa; con `--ajustar` lo encoge hasta 1.15x (más que eso se nota y suena a
locutor apurado) y, si aun así no entra, lo dice en vez de disimularlo.

Sin ningún motor levantado el script igual sirve: genera los subtítulos —que
ya hacen entendible el video en los tres idiomas— y estima el calce de cada
segmento por longitud de texto, para poder corregir el guion antes de
sintetizar nada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUION = os.path.join(RAIZ, "sitio", "narracion", "guion.json")
VIDEO_DIR = os.path.join(RAIZ, "web", "assets", "video")
BASE = os.path.join(VIDEO_DIR, "plania_demo_base.mp4")   # el mudo, sin narrar
GRABADO = os.path.join(VIDEO_DIR, "plania_demo_es.mp4")  # lo que deja grabar_demo.py

IDIOMAS = ["es", "en", "pt"]
NOMBRE = {"es": "Español", "en": "English", "pt": "Português"}

# VoiceBox: estudio de voz local y de código abierto (voicebox.sh). Levanta una
# API REST en la máquina; no hay clave ni costo por carácter.
VOICEBOX_URL = os.environ.get("PLANIA_VOICEBOX_URL", "http://localhost:17493")
REFERENCIA = os.path.join(RAIZ, "sitio", "narracion", "voz_referencia.wav")

# ElevenLabs queda como alternativa. Cobra por carácter y necesita clave.
ELEVEN_MODELO = "eleven_multilingual_v2"   # habla los tres idiomas con la misma voz
ELEVEN_API = "https://api.elevenlabs.io/v1"

# Velocidad de locución para la estimación sin API. Medida sobre narración
# comercial en español rioplatense: ~14 caracteres por segundo a ritmo
# tranquilo. Es una referencia para detectar segmentos claramente pasados de
# largo, no un reemplazo de medir el audio real.
CHARS_POR_SEG = 14.0
TEMPO_MAX = 1.15    # encoger más que esto se escucha

# Subtítulos: dos renglones de ~42 caracteres es lo máximo que se lee cómodo
# en un video de 1280 de ancho sin tapar la pantalla. SUB_MAX_LINEA es el
# objetivo del reparto en dos renglones, no un tope duro: cuando no hay un
# espacio cerca del medio, un renglón puede pasarse unos caracteres antes que
# cortar una palabra.
SUB_MAX_CHARS = 84
SUB_MAX_LINEA = 42
SUB_MIN_SEG = 1.2


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------
def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _correr(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def duracion(path: str) -> float:
    """Duración real de un archivo de audio/video, en segundos.

    Se saca de la salida de ffmpeg y no de ffprobe porque `imageio-ffmpeg`
    trae solo el binario de ffmpeg: pedir ffprobe obligaría al usuario a
    instalar ffmpeg completo en el sistema.
    """
    r = _correr([_ffmpeg(), "-i", path])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------------------------------------------------------------------------
# Guion
# ---------------------------------------------------------------------------
def cargar_guion() -> dict:
    with open(GUION, encoding="utf-8") as f:
        return json.load(f)


def hueco(seg: dict, siguiente: dict | None, fin_video: float) -> float:
    """Segundos disponibles para un segmento antes de pisar al siguiente.

    No se usa `fin` a secas: si el segmento se pasa un poco pero el siguiente
    arranca más tarde, ese aire también es utilizable. Lo que no se puede
    invadir es el `inicio` del que viene.
    """
    tope = siguiente["inicio"] if siguiente else fin_video
    return max(0.0, tope - seg["inicio"])


# ---------------------------------------------------------------------------
# Subtítulos WebVTT
# ---------------------------------------------------------------------------
def _mmss(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def _corte_parejo(texto: str, objetivo: float, solo_espacios: bool = False) -> int:
    """Índice del espacio más cercano a `objetivo` donde cortar.

    Prefiere una coma si hay alguna cerca: cortar en coma se lee como una
    pausa natural, cortar en cualquier espacio parte la frase al medio.
    """
    cerca: list[int] = []
    if not solo_espacios:
        cerca = [m.end() for m in re.finditer(r", ", texto)
                 if abs(m.end() - objetivo) <= len(texto) * 0.22]
    if not cerca:
        cerca = [m.start() for m in re.finditer(r" ", texto)]
    if not cerca:
        return 0
    return min(cerca, key=lambda c: abs(c - objetivo))


def _envolver(texto: str) -> str:
    """Dibuja el cue en uno o dos renglones parejos, sin cortar palabras.

    Se reparte al medio en vez de llenar el primer renglón hasta el tope: el
    llenado codicioso deja un renglón largo y uno de dos palabras, y cuando
    las palabras no encajan justo termina generando un tercer renglón.
    """
    texto = texto.strip()
    if len(texto) <= SUB_MAX_LINEA:
        return texto

    def dividir(corte: int) -> tuple[str, str]:
        return texto[:corte].strip(), texto[corte:].strip()

    corte = _corte_parejo(texto, len(texto) / 2)
    if not corte:
        return texto
    a, b = dividir(corte)
    if max(len(a), len(b)) > SUB_MAX_LINEA:
        # La coma más cercana quedaba demasiado descentrada y dejó un renglón
        # largo: se prefiere el corte parejo aunque no caiga en una pausa.
        corte = _corte_parejo(texto, len(texto) / 2, solo_espacios=True)
        if corte:
            a, b = dividir(corte)
    return f"{a}\n{b}"


# El guion está escrito para que lo LEA una voz sintética, y eso obliga a
# escribir dos cosas distinto de como se muestran:
#
#   1. **El dominio.** "plania.uy" leído literal sale impronunciable en
#      cualquier idioma, así que en el texto hablado va separado en letras.
#      La forma exacta de cada idioma se eligió probando (sintetizando cada
#      variante con la voz clonada y transcribiendo el resultado, repitiendo
#      la prueba para no quedarse con un acierto de casualidad) — no se
#      inventa a criterio.
#   2. **La marca.** El nombre escrito es "Plania" en los tres idiomas — no
#      cambia. Lo que cambia es cómo se escribe en el guion para que la voz
#      pronuncie el juego de palabras: "Planía" (con tilde) en español y
#      portugués, para que el motor le ponga el acento en la í; "Plan A I"
#      en inglés, deletreado, para que se oiga PLAN + AI en vez de leer
#      "Plania" como una palabra inventada.
#
# En el subtítulo ninguna de las dos formas habladas puede aparecer: se
# muestran como se escriben. El orden importa: primero las formas largas,
# que contienen a las cortas.
PARA_LEER = {
    # Dominio — las formas con dominio van antes que las de marca sola: el
    # reemplazo es secuencial, así que si "Plania"/"Planía" se resolviera
    # primero, se comería el prefijo y la forma con dominio dejaría de
    # matchear.
    "Planía punto uy": "plania.uy",
    "Planía ponto uy": "plania.uy",
    "Plan A I dot U Y": "plania.uy",
    "Plania punto u y": "plania.uy",
    "Plania dot u y": "plania.uy",
    "Plania ponto u y": "plania.uy",
    # Marca. En español y portugués se escribe "Planía" (con tilde) para que
    # el motor le ponga el acento en la í; en inglés se deletrea "Plan A I"
    # para que la pronuncie como el juego de palabras PLAN + AI en vez de
    # leerla como una palabra inventada.
    "Planía": "Plania",
    "Plan A I": "Plania",
}


def texto_subtitulo(texto: str) -> str:
    for hablado, escrito in PARA_LEER.items():
        texto = texto.replace(hablado, escrito)
    return texto


def _partir(frase: str) -> list[str]:
    """Parte una oración larga en trozos de a lo sumo dos renglones.

    Se reparte en trozos parejos, no llenando cada uno hasta el tope: llenar
    hasta el tope deja el sobrante como un cue huérfano ("con esos datos el
    lunes a la mañana.") que aparece descolgado de la frase que lo precede.
    """
    frase = frase.strip()
    if len(frase) <= SUB_MAX_CHARS:
        return [frase]
    partes = -(-len(frase) // SUB_MAX_CHARS)          # techo de la división
    objetivo = len(frase) / partes
    trozos, resto = [], frase
    for restantes in range(partes, 1, -1):
        corte = _corte_parejo(resto, objetivo)
        if not corte:
            break
        trozos.append(resto[:corte].strip())
        resto = resto[corte:].strip()
        objetivo = len(resto) / (restantes - 1)
    if resto:
        trozos.append(resto)
    return trozos


def _bloques(texto: str, duracion_total: float) -> list[str]:
    """Bloques de subtítulo: ni de cuatro renglones ni de un parpadeo."""
    frases = [f for f in re.split(r"(?<=[.;?!])\s+", texto.strip()) if f]
    trozos = [t for f in frases for t in _partir(f)]

    # Junta trozos consecutivos mientras entren en dos renglones.
    bloques: list[str] = []
    for t in trozos:
        if bloques and len(bloques[-1]) + 1 + len(t) <= SUB_MAX_CHARS:
            bloques[-1] = f"{bloques[-1]} {t}"
        else:
            bloques.append(t)

    # Y absorbe los que quedarían menos de SUB_MIN_SEG en pantalla: un
    # subtítulo que aparece y desaparece antes de leerlo molesta más que uno
    # apenas más largo. Se lo une al vecino más corto para no desbalancear.
    while len(bloques) > 1:
        total = sum(len(b) for b in bloques)
        cortos = [i for i, b in enumerate(bloques)
                  if duracion_total * len(b) / total < SUB_MIN_SEG]
        if not cortos:
            break
        i = cortos[0]
        if i == 0:
            j = 1
        elif i == len(bloques) - 1:
            j = i - 1
        else:
            j = i - 1 if len(bloques[i - 1]) <= len(bloques[i + 1]) else i + 1
        a, b = min(i, j), max(i, j)
        bloques[a:b + 1] = [f"{bloques[a]} {bloques[b]}"]
    return bloques


def cues(texto: str, inicio: float, fin: float) -> list[tuple[float, float, str]]:
    """Parte un segmento en subtítulos con sus tiempos.

    El reparto de tiempo es proporcional a la cantidad de caracteres de cada
    bloque: aproxima bien porque dentro de un mismo idioma la velocidad de
    lectura es pareja, y evita que un bloque corto quede en pantalla lo mismo
    que uno largo.

    El corte es por fin de oración y no por dos puntos: cortar en ":" parte
    "El panel arranca con lo que importa:" de su enumeración y deja un cue de
    tres palabras seguido de uno larguísimo.
    """
    duracion_total = max(0.5, fin - inicio)
    bloques = _bloques(texto_subtitulo(texto), duracion_total)
    total = sum(len(b) for b in bloques) or 1

    salida, t = [], inicio
    for i, b in enumerate(bloques):
        t_fin = fin if i == len(bloques) - 1 else min(fin, t + duracion_total * len(b) / total)
        salida.append((t, t_fin, _envolver(b)))
        t = t_fin
    return salida


def escribir_vtt(guion: dict, idioma: str) -> str:
    destino = os.path.join(VIDEO_DIR, f"plania_demo_{idioma}.vtt")
    lineas = ["WEBVTT", "", f"NOTE Plania · {NOMBRE[idioma]}", ""]
    n = 0
    for seg in guion["segmentos"]:
        for ini, fin, texto in cues(seg[idioma], seg["inicio"], seg["fin"]):
            n += 1
            lineas += [str(n), f"{_mmss(ini)} --> {_mmss(fin)}", texto, ""]
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    return destino


# ---------------------------------------------------------------------------
# Informe de calce (con o sin API)
# ---------------------------------------------------------------------------
def estimar(texto: str) -> float:
    return len(texto) / CHARS_POR_SEG


def informe_estimado(guion: dict) -> int:
    """Avisa qué segmentos no entrarían en su hueco. Devuelve cuántos.

    Corre sin API key: sirve para ajustar el guion antes de pagar síntesis.
    """
    segs = guion["segmentos"]
    fin_video = float(guion.get("duracion_seg", 0)) or segs[-1]["fin"]
    problemas = 0
    print("\n  segmento        hueco        es        en        pt")
    print("  " + "-" * 52)
    for i, s in enumerate(segs):
        h = hueco(s, segs[i + 1] if i + 1 < len(segs) else None, fin_video)
        fila = f"  {s['id']:<14} {h:5.1f}s"
        for l in IDIOMAS:
            e = estimar(s[l])
            marca = " " if e <= h else "!"
            fila += f"   {e:5.1f}{marca}"
            if e > h:
                problemas += 1
        print(fila)
    print("  " + "-" * 52)
    if problemas:
        print(f"  ! {problemas} caso(s) donde el texto estimado no entra en su hueco.")
        print("    Acortá el texto en sitio/narracion/guion.json o corré con --ajustar.")
    else:
        print("  Todos los segmentos entran en su hueco (estimado por longitud).")
    return problemas


# ---------------------------------------------------------------------------
# Síntesis
# ---------------------------------------------------------------------------
def _guardar_audio(r, destino: str) -> bool:
    """Guarda lo que devolvió el motor, venga como audio o como JSON.

    Los motores locales no coinciden en esto: algunos devuelven los bytes del
    audio, otros un JSON con la ruta del archivo que acaban de escribir o con
    el audio en base64. Se cubren los tres casos en vez de atarse a uno.
    """
    import base64
    import shutil as _sh

    tipo = (r.headers.get("content-type") or "").lower()
    if "json" not in tipo:
        with open(destino, "wb") as f:
            f.write(r.content)
        return True

    d = r.json()
    if isinstance(d, dict):
        for clave in ("audio_base64", "audio", "data"):
            if isinstance(d.get(clave), str) and len(d[clave]) > 100:
                with open(destino, "wb") as f:
                    f.write(base64.b64decode(d[clave]))
                return True
        for clave in ("path", "file", "file_path", "output_path", "audio_path"):
            ruta = d.get(clave)
            if isinstance(ruta, str) and os.path.exists(ruta):
                _sh.copy(ruta, destino)
                return True
    print(f"    el motor respondió JSON sin audio reconocible: {str(d)[:200]}")
    return False


def voicebox_perfiles() -> list[dict]:
    """Perfiles de voz cargados en VoiceBox."""
    import requests

    r = requests.get(f"{VOICEBOX_URL}/profiles", timeout=20)
    r.raise_for_status()
    d = r.json()
    return d.get("profiles", d) if isinstance(d, dict) else d


def voicebox_crear_perfil(nombre: str, muestra: str, idioma: str = "es") -> str:
    """Clona la voz de `muestra` y devuelve el id del perfil creado.

    Se intenta primero con multipart —que es como se sube un archivo— y si el
    servidor lo rechaza se reintenta mandando la ruta en JSON. VoiceBox corre
    en la misma máquina, así que pasarle una ruta local es válido; el
    multipart cubre el caso de que corra en otra.
    """
    import requests

    if not os.path.exists(muestra):
        raise SystemExit(f"No está la muestra de voz: {muestra}")

    intentos = []
    try:
        with open(muestra, "rb") as f:
            r = requests.post(f"{VOICEBOX_URL}/profiles",
                              data={"name": nombre, "language": idioma},
                              files={"file": (os.path.basename(muestra), f, "audio/wav")},
                              timeout=300)
        if r.ok:
            d = r.json()
            return str(d.get("profile_id") or d.get("id") or d)
        intentos.append(f"multipart -> {r.status_code} {r.text[:150]}")
    except Exception as e:
        intentos.append(f"multipart -> {str(e)[:150]}")

    try:
        r = requests.post(f"{VOICEBOX_URL}/profiles",
                          json={"name": nombre, "language": idioma,
                                "sample_path": os.path.abspath(muestra)},
                          timeout=300)
        if r.ok:
            d = r.json()
            return str(d.get("profile_id") or d.get("id") or d)
        intentos.append(f"json -> {r.status_code} {r.text[:150]}")
    except Exception as e:
        intentos.append(f"json -> {str(e)[:150]}")

    raise SystemExit(
        "No se pudo crear el perfil de voz por API:\n  " + "\n  ".join(intentos) +
        f"\n\nCreálo a mano en VoiceBox importando {muestra}, y pasá el id con "
        f"--voz. El contrato exacto de la API está en {VOICEBOX_URL}/docs.")


def sintetizar_voicebox(texto: str, perfil: str, idioma: str, destino: str) -> bool:
    import requests

    try:
        r = requests.post(f"{VOICEBOX_URL}/generate",
                          json={"text": texto, "profile_id": perfil, "language": idioma},
                          timeout=600)
        r.raise_for_status()
    except Exception as e:
        print(f"    error de síntesis: {str(e)[:200]}")
        return False
    return _guardar_audio(r, destino)


# --- Motor local sin servidor -------------------------------------------
# Chatterbox Multilingual (MIT, de Resemble AI) clona una voz desde una
# muestra de audio y habla 23 idiomas, entre ellos los tres que necesitamos.
# Es el mismo motor que trae VoiceBox adentro; acá se usa directo, sin la
# aplicación de escritorio, para poder doblar desde una terminal o desde CI.
#
# La licencia MIT importa: esto se usa para el video de un producto que se
# vende. Otros modelos de clonación con calidad parecida (XTTS-v2, algunos
# checkpoints de F5) son de uso no comercial y no servirían acá.
_MODELO_LOCAL = None


def _cargar_modelo_local():
    global _MODELO_LOCAL
    if _MODELO_LOCAL is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        import torch
        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"  cargando el modelo de voz en {dispositivo} "
              f"(la primera vez se descarga, tarda)…")
        _MODELO_LOCAL = ChatterboxMultilingualTTS.from_pretrained(device=dispositivo)
    return _MODELO_LOCAL


def sintetizar_local(texto: str, referencia: str, idioma: str, destino: str) -> bool:
    """Clona la voz de `referencia` y le hace decir `texto` en `idioma`."""
    try:
        import torchaudio
        modelo = _cargar_modelo_local()
        wav = modelo.generate(texto, language_id=idioma, audio_prompt_path=referencia)
        # torchaudio deduce el formato de la extensión y no acepta que se lo
        # digan por parámetro, así que se escribe como .wav y se renombra: los
        # segmentos llevan una extensión genérica, la misma para los tres
        # motores, y ffmpeg después detecta el formato por contenido.
        temporal = destino + ".wav"
        torchaudio.save(temporal, wav, modelo.sr)
        os.replace(temporal, destino)
    except Exception as e:
        print(f"    error de síntesis local: {str(e)[:200]}")
        return False
    return True


def sintetizar_elevenlabs(texto: str, voice_id: str, api_key: str, destino: str,
                          estabilidad: float = 0.45, similaridad: float = 0.80) -> bool:
    """Alternativa paga. `estabilidad` algo baja (0.45) da una lectura con más
    intención, que es lo que se busca en un video de venta; subirla la vuelve
    plana."""
    import requests

    try:
        r = requests.post(
            f"{ELEVEN_API}/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "content-type": "application/json",
                     "accept": "audio/mpeg"},
            json={"text": texto, "model_id": ELEVEN_MODELO,
                  "voice_settings": {"stability": estabilidad,
                                     "similarity_boost": similaridad}},
            timeout=120,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"    error de síntesis: {str(e)[:200]}")
        return False
    return _guardar_audio(r, destino)


def mezclar(base: str, piezas: list[tuple[str, float, float]], destino: str,
            fin_video: float) -> None:
    """Pega la narración sobre el video mudo.

    Cada pieza es (archivo, retardo en segundos, tempo). Se arma una pista de
    silencio del largo del video y se mezclan encima los segmentos ya
    retrasados a su marca: así el audio dura exactamente lo que dura la
    imagen aunque el último segmento termine antes.
    """
    ff = _ffmpeg()
    args = [ff, "-y", "-i", base]
    for archivo, _, _ in piezas:
        args += ["-i", archivo]

    filtros = [f"anullsrc=r=44100:cl=stereo,atrim=0:{fin_video:.3f}[fondo]"]
    etiquetas = ["[fondo]"]
    for i, (_, retardo, tempo) in enumerate(piezas, start=1):
        ms = int(round(retardo * 1000))
        cadena = f"[{i}:a]aresample=44100"
        if abs(tempo - 1.0) > 0.001:
            cadena += f",atempo={tempo:.4f}"
        cadena += f",adelay={ms}|{ms}[s{i}]"
        filtros.append(cadena)
        etiquetas.append(f"[s{i}]")

    # normalize=0: con la normalización por defecto amix divide el volumen
    # entre la cantidad de entradas, así que la voz quedaría casi inaudible
    # al haber seis segmentos más el silencio de fondo.
    filtros.append("".join(etiquetas) +
                   f"amix=inputs={len(etiquetas)}:normalize=0:dropout_transition=0[mix]")

    args += ["-filter_complex", ";".join(filtros),
             "-map", "0:v", "-map", "[mix]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", "-shortest", destino]
    r = _correr(args)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg falló al mezclar:\n{(r.stderr or '')[-1500:]}")


def doblar(guion: dict, idioma: str, voz: str, motor: str, api_key: str,
           ajustar: bool) -> int:
    """Sintetiza, controla solapamientos y deja plania_demo_<idioma>.mp4.

    Devuelve la cantidad de segmentos que quedaron pisando al siguiente.
    """
    segs = guion["segmentos"]
    fin_video = float(guion.get("duracion_seg", 0)) or duracion(BASE)
    tmp = os.path.join(VIDEO_DIR, f"_voz_{idioma}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    piezas: list[tuple[str, float, float]] = []
    pisados = 0
    print(f"\n[{idioma}] narrando con la voz {voz} · motor {motor}")

    for i, s in enumerate(segs):
        h = hueco(s, segs[i + 1] if i + 1 < len(segs) else None, fin_video)
        archivo = os.path.join(tmp, f"{i:02d}_{s['id']}.audio")
        if motor == "local":
            ok = sintetizar_local(s[idioma], voz, idioma, archivo)
        elif motor == "voicebox":
            ok = sintetizar_voicebox(s[idioma], voz, idioma, archivo)
        else:
            ok = sintetizar_elevenlabs(s[idioma], voz, api_key, archivo)
        if not ok:
            shutil.rmtree(tmp, ignore_errors=True)
            raise SystemExit(f"[{idioma}] no se pudo sintetizar '{s['id']}'.")

        real = duracion(archivo)
        tempo = 1.0
        nota = ""
        if real > h:
            if ajustar:
                tempo = min(TEMPO_MAX, real / h) if h > 0 else TEMPO_MAX
                final = real / tempo
                if final > h:
                    pisados += 1
                    nota = (f"  ! aun a {tempo:.2f}x sobran {final - h:.1f}s: "
                            f"acortá el texto de '{s['id']}' en {idioma}")
                else:
                    nota = f"  ajustado a {tempo:.2f}x"
            else:
                pisados += 1
                nota = f"  ! se pasa {real - h:.1f}s y pisaría al siguiente"
        print(f"  {s['id']:<10} {real:5.1f}s / {h:5.1f}s{nota}")
        piezas.append((archivo, s["inicio"], tempo))

    # Un doblaje con segmentos pisándose no puede reemplazar al que ya está
    # publicado: se escribe aparte, con un nombre que no sirve para publicar,
    # para poder escucharlo y decidir qué acortar.
    nombre = f"plania_demo_{idioma}" + (".REVISAR.mp4" if pisados else ".mp4")
    destino = os.path.join(VIDEO_DIR, nombre)
    mezclar(BASE, piezas, destino, fin_video)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  -> {os.path.relpath(destino, RAIZ)} "
          f"({os.path.getsize(destino) / 1_048_576:.1f} MB)"
          + ("  (no se publica: hay solapamientos)" if pisados else ""))
    return pisados


# ---------------------------------------------------------------------------
def preparar_base() -> None:
    """Deja el video mudo en plania_demo_base.mp4.

    La grabación se llama `plania_demo_es.mp4`, que es también el nombre del
    video doblado al español. Se guarda el mudo aparte para poder re-doblar
    las veces que haga falta sin tener que volver a grabar el producto.
    """
    if os.path.exists(BASE):
        return
    if not os.path.exists(GRABADO):
        raise SystemExit("Falta el video. Corré primero sitio/grabar_demo.py")
    if duracion_tiene_audio(GRABADO):
        raise SystemExit(f"{GRABADO} ya tiene audio: no se puede usar como base.\n"
                         "Volvé a grabar con sitio/grabar_demo.py.")
    shutil.copy(GRABADO, BASE)
    print(f"[base] {os.path.relpath(BASE, RAIZ)} (video mudo guardado aparte)")


def duracion_tiene_audio(path: str) -> bool:
    r = _correr([_ffmpeg(), "-i", path])
    return "Audio:" in (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Doblaje trilingüe del video de Plania")
    ap.add_argument("--doblar", action="store_true", help="sintetizar la voz")
    ap.add_argument("--ajustar", action="store_true",
                    help="encoger hasta 1.15x los segmentos que no entren")
    ap.add_argument("--motor", default=os.environ.get("PLANIA_MOTOR_VOZ", "local"),
                    choices=["local", "voicebox", "elevenlabs"],
                    help="local: clona sin servidor ni cuenta (por defecto); "
                         "voicebox: la app de escritorio; elevenlabs: pago")
    ap.add_argument("--voz", default=os.environ.get("PLANIA_VOICE_ID", ""),
                    help="id del perfil de voz (o variable PLANIA_VOICE_ID)")
    ap.add_argument("--listar-voces", action="store_true",
                    help="mostrar los perfiles de voz cargados en VoiceBox")
    ap.add_argument("--crear-voz", metavar="NOMBRE",
                    help="clonar sitio/narracion/voz_referencia.wav como perfil nuevo")
    ap.add_argument("--idiomas", default=",".join(IDIOMAS))
    args = ap.parse_args()

    if args.listar_voces:
        perfiles = voicebox_perfiles()
        if not perfiles:
            print(f"VoiceBox no tiene perfiles cargados ({VOICEBOX_URL}).")
            print(f"Creá uno con: python3 sitio/doblar_video.py --crear-voz \"Plania\"")
            return 1
        for p in perfiles:
            print(f"  {p.get('id') or p.get('profile_id')}  {p.get('name', '')}")
        return 0

    if args.crear_voz:
        perfil = voicebox_crear_perfil(args.crear_voz, REFERENCIA)
        print(f"Perfil creado: {perfil}")
        print(f"Usalo así:\n  python3 sitio/doblar_video.py --doblar --voz {perfil}")
        return 0

    guion = cargar_guion()
    idiomas = [i.strip() for i in args.idiomas.split(",") if i.strip() in IDIOMAS]

    os.makedirs(VIDEO_DIR, exist_ok=True)
    print("[subtítulos]")
    for idioma in idiomas:
        ruta = escribir_vtt(guion, idioma)
        print(f"  {os.path.relpath(ruta, RAIZ)}")

    informe_estimado(guion)

    if not args.doblar:
        print("\nSubtítulos listos: el video ya se entiende en los tres idiomas.")
        print("Para la voz, con VoiceBox corriendo:\n"
              "  python3 sitio/doblar_video.py --crear-voz \"Plania\"\n"
              "  python3 sitio/doblar_video.py --doblar --voz <id>")
        return 0

    api_key = ""
    if args.motor == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if len(api_key) < 10:
            print("\nFalta ELEVENLABS_API_KEY. VoiceBox no la necesita: "
                  "--motor voicebox")
            return 1

    voz = args.voz
    if args.motor == "local":
        # Acá la 'voz' no es un id sino la muestra que se clona.
        voz = voz or REFERENCIA
        if not os.path.exists(voz):
            print(f"\nNo está la muestra de voz: {voz}")
            return 1
    if not voz and args.motor == "voicebox":
        # Con un solo perfil cargado no tiene sentido obligar a copiar el id.
        try:
            perfiles = voicebox_perfiles()
        except Exception as e:
            print(f"\nNo se pudo hablar con VoiceBox en {VOICEBOX_URL}: {str(e)[:150]}\n"
                  "Levantá VoiceBox (voicebox.sh) o indicá otra dirección en "
                  "PLANIA_VOICEBOX_URL.")
            return 1
        if len(perfiles) == 1:
            voz = str(perfiles[0].get("id") or perfiles[0].get("profile_id"))
            print(f"[voz] único perfil cargado: {voz}")
    if not voz:
        print("\nFalta el perfil de voz. Para que sea la misma voz del video "
              "original:\n"
              "  python3 sitio/doblar_video.py --crear-voz \"Plania\"\n"
              "  python3 sitio/doblar_video.py --listar-voces")
        return 1

    preparar_base()
    pisados = sum(doblar(guion, i, voz, args.motor, api_key, args.ajustar)
                  for i in idiomas)
    if pisados:
        print(f"\n! {pisados} segmento(s) siguen pisando al siguiente. "
              "Acortá esos textos en sitio/narracion/guion.json y volvé a correr.")
        return 2
    print("\nListo: tres videos narrados con la misma voz y sin solapamientos.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
