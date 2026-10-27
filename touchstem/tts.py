"""Natural voice for Russian and Kazakh: neural Piper voices (ru: Irina, kk: ISSAI high).

* Text shown on screen stays as is; only the spoken version is normalised:
  numbers become words with proper grammar ("2,63 В" -> "две целых шестьдесят три сотых вольта",
  kk: "екі бүтін жүзден алпыс үш вольт"), "№" -> "номер", minus signs are read.
* Audio is cached as small MP3 files in static/tts/<key>.mp3, key = sha1("lang|text")[:20].
  The browser computes the same key from the text it is about to say and plays the file;
  if it is not there yet, it falls back to the phone's own voice.
* Voices (~60 MB and ~130 MB) are downloaded once from the Piper GitHub release.
"""
from __future__ import annotations

import hashlib
from collections import deque
import io
import os
import re
import tarfile
import threading
import urllib.request
import wave
from pathlib import Path

from num2words import num2words

ROOT = Path(__file__).resolve().parents[1]
TTS_DIR = ROOT / "static" / "tts"
VOICE_DIR = Path(os.environ.get("TOUCHSTEM_VOICES", Path.home() / ".cache" / "touchstem" / "voices"))
RELEASE = "https://github.com/rhasspy/piper/releases/download/v0.0.2/{name}.tar.gz"
VOICES = {"ru": ("voice-ru-irinia-medium", "ru-irinia-medium.onnx", 1.05),
          "kk": ("voice-kk-issai-high", "kk-issai-high.onnx", 1.08)}

# ------------------------------------------------------------------ text normalisation
RU_UNITS = {  # (1, 2-4 / fractions, 5+)
    "В": ("вольт", "вольта", "вольт"), "мВ": ("милливольт", "милливольта", "милливольт"),
    "кВ": ("киловольт", "киловольта", "киловольт"), "А": ("ампер", "ампера", "ампер"),
    "мА": ("миллиампер", "миллиампера", "миллиампер"), "мкА": ("микроампер", "микроампера", "микроампер"),
    "Ом": ("ом", "ома", "ом"), "кОм": ("килоом", "килоома", "килоом"), "МОм": ("мегаом", "мегаома", "мегаом"),
    "Вт": ("ватт", "ватта", "ватт"), "мВт": ("милливатт", "милливатта", "милливатт"), "кВт": ("киловатт", "киловатта", "киловатт"),
    "Ф": ("фарад", "фарада", "фарад"), "мкФ": ("микрофарад", "микрофарада", "микрофарад"), "Гц": ("герц", "герца", "герц"),
    "мм": ("миллиметр", "миллиметра", "миллиметров"), "см": ("сантиметр", "сантиметра", "сантиметров"),
    "м": ("метр", "метра", "метров"), "кг": ("килограмм", "килограмма", "килограммов"), "г": ("грамм", "грамма", "граммов"),
}
KK_UNITS = {"В": "вольт", "мВ": "милливольт", "кВ": "киловольт", "А": "ампер", "мА": "миллиампер", "мкА": "микроампер",
            "Ом": "ом", "кОм": "килоом", "МОм": "мегаом", "Вт": "ватт", "мВт": "милливатт", "кВт": "киловатт",
            "Ф": "фарад", "мкФ": "микрофарад", "Гц": "герц", "мм": "миллиметр", "см": "сантиметр", "м": "метр",
            "кг": "килограмм", "г": "грамм"}
WORD_FORMS = {w: forms for forms in RU_UNITS.values() for w in forms}
KK_FRACTION = {10: "оннан", 100: "жүзден", 1000: "мыңнан"}
UNIT_RE = "|".join(sorted(set(RU_UNITS) | set(WORD_FORMS) | set(KK_UNITS.values()), key=len, reverse=True))
NUM_RE = re.compile(r"(?<![\w,])(-|−|минус\s)?(\d+)(?:,(\d+))?(?:\s?(" + UNIT_RE + r"))?(?![\w])")


def _ru_plural(n: int, forms) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def _number_words(intpart: str, frac: str | None, lang: str) -> str:
    if lang == "kk":
        words = num2words(int(intpart), lang="kz")
        if frac:
            frac = frac[:3]
            words += f" бүтін {KK_FRACTION[10 ** len(frac)]} {num2words(int(frac), lang='kz')}"
        return words
    return num2words(float(f"{intpart}.{frac}") if frac else int(intpart), lang="ru")


def speakable(text: str, lang: str = "ru") -> str:
    s = text.replace("№", "номер " if lang == "ru" else "нөмір ")
    s = re.sub(r"\bx\b", "икс", s)
    s = re.sub(r"\by\b", "игрек", s)

    def repl(m):
        sign, ip, fr, unit = m.groups()
        words = _number_words(ip, fr, lang)
        if sign:
            words = ("минус " if lang == "ru" else "минус ") + words
        if unit:
            if lang == "kk":
                words += " " + KK_UNITS.get(unit, unit)
            else:
                forms = RU_UNITS.get(unit) or WORD_FORMS.get(unit)
                if forms:
                    words += " " + (forms[1] if fr else _ru_plural(int(ip), forms))
                else:
                    words += " " + unit
        return words

    s = NUM_RE.sub(repl, s)
    s = s.replace(" — ", ", ").replace("—", ", ")
    return re.sub(r"\s+", " ", s).strip()


def key(text: str, lang: str) -> str:
    return hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------ synthesis
_voices: dict = {}
_lock = threading.Lock()
_pending: set[str] = set()
_queue: deque = deque()          # newest sheet first: what the teacher is looking at now gets voiced first
_wake = threading.Condition()
_worker: threading.Thread | None = None


def _run() -> None:
    while True:
        with _wake:
            while not _queue:
                _wake.wait()
            text, lang = _queue.popleft()
        _job(text, lang)


def _model_path(lang: str) -> Path:
    name, onnx, _ = VOICES[lang]
    path = VOICE_DIR / name / onnx
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / "download.tar.gz"
        urllib.request.urlretrieve(RELEASE.format(name=name), tmp)
        with tarfile.open(tmp) as tf:
            for member in tf.getmembers():
                if member.name.endswith((".onnx", ".onnx.json")) and "/" not in member.name.strip("./"):
                    tf.extract(member, path.parent, filter="data")
        tmp.unlink(missing_ok=True)
    return path


def _voice(lang: str):
    with _lock:
        if lang not in _voices:
            from piper import PiperVoice
            _voices[lang] = PiperVoice.load(str(_model_path(lang)))
        return _voices[lang]


def available() -> bool:
    try:
        import lameenc  # noqa: F401
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def synth_mp3(text: str, lang: str) -> bytes:
    from piper import SynthesisConfig
    import lameenc

    voice = _voice(lang)
    cfg = SynthesisConfig(length_scale=VOICES[lang][2], noise_scale=0.6, noise_w_scale=0.8)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(speakable(text, lang), w, syn_config=cfg)
    buf.seek(0)
    with wave.open(buf) as w:
        rate, pcm = w.getframerate(), w.readframes(w.getnframes())
    enc = lameenc.Encoder()
    enc.set_bit_rate(48)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    return enc.encode(pcm) + enc.flush()


def _job(text: str, lang: str) -> None:
    k = key(text, lang)
    try:
        out = TTS_DIR / f"{k}.mp3"
        if not out.exists():
            data = synth_mp3(text, lang)
            TTS_DIR.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(out)
    except Exception as exc:  # voice download or synthesis failed: the browser voice takes over
        print(f"[tts] {lang}: {exc}")
    finally:
        _pending.discard(k)


def ensure(texts: list[str], lang: str) -> tuple[int, int]:
    """Queue missing phrases for synthesis in the background. Returns (ready, total)."""
    if not available():
        return 0, len(texts)
    global _worker
    uniq = list(dict.fromkeys(t for t in texts if t and t.strip()))
    ready, todo = 0, []
    for t in uniq:
        k = key(t, lang)
        if (TTS_DIR / f"{k}.mp3").exists():
            ready += 1
        elif k not in _pending:
            _pending.add(k)
            todo.append((t, lang))
    if todo:
        with _wake:
            _queue.extendleft(reversed(todo))
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_run, name="tts", daemon=True)
                _worker.start()
            _wake.notify()
    return ready, len(uniq)


def status(texts: list[str], lang: str) -> tuple[int, int]:
    uniq = list(dict.fromkeys(t for t in texts if t and t.strip()))
    return sum((TTS_DIR / f"{key(t, lang)}.mp3").exists() for t in uniq), len(uniq)
