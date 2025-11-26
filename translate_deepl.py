import json
import os
import time
from pathlib import Path

import requests

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
if not DEEPL_API_KEY:
    raise SystemExit("Missing DEEPL_API_KEY env var")

# Ajusta estos paths
INPUT_PATH = Path("en.json")
OUTPUT_PATH = Path("fr-FR.json")

# Idioma destino DeepL: FR, PT-BR, DE, ZH, KO…
TARGET_LANG = "FR"  # o "PT-BR", "DE", "ZH", "KO", etc.

DEEPL_ENDPOINT = "https://api-free.deepl.com/v2/translate"
# Para API de pago:
# DEEPL_ENDPOINT = "https://api.deepl.com/v2/translate"

BATCH_SIZE = 50  # cuántas cadenas enviar por request


def translate_batch(texts: list[str]) -> list[str]:
    """Envía un batch de textos a DeepL y devuelve la lista de traducciones."""
    data = {
        "auth_key": DEEPL_API_KEY,
        "target_lang": TARGET_LANG,
        # Opcional:
        # "preserve_formatting": "1",
    }
    # DeepL permite múltiples parámetros text
    for t in texts:
        data.setdefault("text", [])
        data["text"].append(t)

    response = requests.post(DEEPL_ENDPOINT, data=data, timeout=60)
    if not response.ok:
        raise RuntimeError(f"DeepL error {response.status_code}: {response.text}")

    payload = response.json()
    translations = payload.get("translations", [])
    if len(translations) != len(texts):
        raise RuntimeError("Mismatch between input texts and translations")

    return [t["text"] for t in translations]


def main():
    raw = INPUT_PATH.read_text("utf-8")
    data: dict[str, str] = json.loads(raw)

    items = list(data.items())
    translated: dict[str, str] = {}

    total = len(items)
    print(f"Translating {total} entries to {TARGET_LANG}...")

    for i in range(0, total, BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        keys = [k for k, _ in batch]
        values = [v for _, v in batch]

        try:
            translated_values = translate_batch(values)
        except Exception as e:
            print(f"Error translating batch {i}-{i+len(batch)}: {e}")
            # opcional: sleep/retry si hay rate limit
            time.sleep(5)
            raise

        for k, tv in zip(keys, translated_values, strict=True):
            translated[k] = tv

        print(f"Translated {min(i + BATCH_SIZE, total)}/{total}")

        # opcional: evitar rate limit
        time.sleep(0.5)

    OUTPUT_PATH.write_text(json.dumps(translated, ensure_ascii=False, indent=2), "utf-8")
    print(f"Done. Written: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
