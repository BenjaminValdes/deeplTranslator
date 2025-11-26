import json
import os
from dotenv import load_dotenv
import time
from pathlib import Path
import requests


load_dotenv()

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
if not DEEPL_API_KEY:
    raise SystemExit("Missing DEEPL_API_KEY env var")

# -----------------------------------------------
# Pedir datos al usuario
# -----------------------------------------------

# El archivo JSON debe estar en el mismo directorio, o de lo contrario pasar la ruta completa
def ask_inputs():
    print("=== DeepL Translation Script ===")

    input_path_str = input("Path del archivo de entrada (ej: en.json): ").strip()
    output_path_str = input("Path del archivo de salida (ej: fr-FR.json): ").strip()
    target_lang = input("Idioma destino DeepL (ej: FR, PT-BR, DE, ZH): ").strip().upper()

    if not input_path_str:
        raise ValueError("Debe ingresar el path del archivo de entrada.")
    if not output_path_str:
        raise ValueError("Debe ingresar el path del archivo de salida.")
    if not target_lang:
        raise ValueError("Debe ingresar un idioma destino.")

    return Path(input_path_str), Path(output_path_str), target_lang

# Configuración
DEEPL_ENDPOINT = "https://api.deepl.com/v2/translate"
BATCH_SIZE = 50

# -----------------------------------------------
# Traducción por batches
# -----------------------------------------------
def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    data = {
        "auth_key": DEEPL_API_KEY,
        "target_lang": target_lang,
    }

    for t in texts:
        data.setdefault("text", [])
        data["text"].append(t)

    response = requests.post(DEEPL_ENDPOINT, data=data, timeout=60)
    if not response.ok:
        raise RuntimeError(f"DeepL error {response.status_code}: {response.text}")

    payload = response.json()
    translations = payload.get("translations", [])

    if len(translations) != len(texts):
        raise RuntimeError("Mismatch entre textos enviados y traducidos")

    return [t["text"] for t in translations]


# -----------------------------------------------
# Main
# -----------------------------------------------
def main():
    INPUT_PATH, OUTPUT_PATH, TARGET_LANG = ask_inputs()

    raw = INPUT_PATH.read_text("utf-8")
    data: dict[str, str] = json.loads(raw)

    items = list(data.items())
    translated: dict[str, str] = {}

    total = len(items)
    print(f"\nTraduciendo {total} entries a {TARGET_LANG}...\n")

    for i in range(0, total, BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        keys = [k for k, _ in batch]
        values = [v for _, v in batch]

        try:
            translated_values = translate_batch(values, TARGET_LANG)
        except Exception as e:
            print(f"Error traduciendo batch {i}-{i+len(batch)}: {e}")
            time.sleep(5)
            raise

        for k, tv in zip(keys, translated_values, strict=True):
            translated[k] = tv

        print(f"Traducidas {min(i + BATCH_SIZE, total)}/{total}")

        time.sleep(0.5)

    OUTPUT_PATH.write_text(
        json.dumps(translated, ensure_ascii=False, indent=2),
        "utf-8",
    )

    print(f"\nListo! Archivo generado: {OUTPUT_PATH}\n")


if __name__ == "__main__":
    main()
