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
ElevenLabs `eleven_multilingual_v2` toma un `voice_id` y lo hace hablar
cualquiera de los idiomas que soporta. No es una voz por idioma: es la
misma voz. Por eso el doblaje conserva el timbre de la versión original en
inglés y portugués, en vez de sonar a tres locutores distintos.

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

Sin `ELEVENLABS_API_KEY` el script igual sirve: genera los subtítulos —que
ya hacen entendible el video en los tres idiomas— y estima el calce de cada
segmento por longitud de texto, para poder corregir el guion antes de
gastar créditos de síntesis.
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

MODELO = "eleven_multilingual_v2"   # el que habla los tres idiomas con la misma voz
API = "https://api.elevenlabs.io/v1"

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


# El guion está escrito para que lo LEA una voz sintética, así que el dominio
# va deletreado ("Plania punto u y") — si no, el TTS lee "plania.uy" como una
# sola palabra impronunciable. En el subtítulo eso quedaría ridículo, así que
# se escribe como se escribe.
PARA_LEER = {
    "Plania punto u y": "plania.uy",
    "Plania dot u y": "plania.uy",
    "Plania ponto u y": "plania.uy",
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
def sintetizar(texto: str, voice_id: str, api_key: str, destino: str,
               estabilidad: float = 0.45, similaridad: float = 0.80) -> bool:
    """Un segmento de narración a MP3. Devuelve si salió bien.

    `estabilidad` algo baja (0.45) da una lectura con más intención, que es
    lo que se busca en un video de venta; subirla la vuelve plana.
    """
    import requests

    try:
        r = requests.post(
            f"{API}/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "content-type": "application/json",
                     "accept": "audio/mpeg"},
            json={"text": texto, "model_id": MODELO,
                  "voice_settings": {"stability": estabilidad,
                                     "similarity_boost": similaridad}},
            timeout=120,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"    error de síntesis: {str(e)[:200]}")
        return False
    with open(destino, "wb") as f:
        f.write(r.content)
    return True


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


def doblar(guion: dict, idioma: str, voice_id: str, api_key: str,
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
    print(f"\n[{idioma}] narrando con la voz {voice_id} · {MODELO}")

    for i, s in enumerate(segs):
        h = hueco(s, segs[i + 1] if i + 1 < len(segs) else None, fin_video)
        archivo = os.path.join(tmp, f"{i:02d}_{s['id']}.mp3")
        if not sintetizar(s[idioma], voice_id, api_key, archivo):
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

    destino = os.path.join(VIDEO_DIR, f"plania_demo_{idioma}.mp4")
    mezclar(BASE, piezas, destino, fin_video)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  -> {os.path.relpath(destino, RAIZ)} "
          f"({os.path.getsize(destino) / 1_048_576:.1f} MB)")
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
    ap.add_argument("--doblar", action="store_true",
                    help="sintetizar la voz (requiere ELEVENLABS_API_KEY)")
    ap.add_argument("--ajustar", action="store_true",
                    help="encoger hasta 1.15x los segmentos que no entren")
    ap.add_argument("--voz", default=os.environ.get("PLANIA_VOICE_ID", ""),
                    help="voice_id de ElevenLabs (o variable PLANIA_VOICE_ID)")
    ap.add_argument("--idiomas", default=",".join(IDIOMAS))
    args = ap.parse_args()

    guion = cargar_guion()
    idiomas = [i.strip() for i in args.idiomas.split(",") if i.strip() in IDIOMAS]

    os.makedirs(VIDEO_DIR, exist_ok=True)
    print("[subtítulos]")
    for idioma in idiomas:
        ruta = escribir_vtt(guion, idioma)
        print(f"  {os.path.relpath(ruta, RAIZ)}")

    problemas = informe_estimado(guion)

    if not args.doblar:
        print("\nSubtítulos listos: el video ya se entiende en los tres idiomas.")
        print("Para la voz: ELEVENLABS_API_KEY=... PLANIA_VOICE_ID=... "
              "python3 sitio/doblar_video.py --doblar")
        return 0

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if len(api_key) < 10:
        print("\nFalta ELEVENLABS_API_KEY: no se sintetiza nada.")
        return 1
    if not args.voz:
        print("\nFalta el voice_id. Para que la voz sea la misma que en el video "
              "original hay que pasar la de ese video:\n"
              "  PLANIA_VOICE_ID=<voice_id> python3 sitio/doblar_video.py --doblar")
        return 1

    preparar_base()
    pisados = sum(doblar(guion, i, args.voz, api_key, args.ajustar) for i in idiomas)
    if pisados:
        print(f"\n! {pisados} segmento(s) siguen pisando al siguiente. "
              "Acortá esos textos en sitio/narracion/guion.json y volvé a correr.")
        return 2
    print("\nListo: tres videos narrados con la misma voz y sin solapamientos.")
    return 0 if problemas == 0 else 0


if __name__ == "__main__":
    sys.path.insert(0, RAIZ)
    raise SystemExit(main())
