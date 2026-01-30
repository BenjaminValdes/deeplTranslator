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

# Configuración
DEEPL_ENDPOINT = "https://api.deepl.com/v2/translate"
BATCH_SIZE = 50

# Lista de idiomas por defecto
DEFAULT_TARGET_LANGS = ["EN", "PT-BR", "IT", "DE", "FR", "KO", "ZH-HANS"]

# Pedir datos al usuario

# El archivo JSON debe estar en el mismo directorio, o de lo contrario pasar la ruta completa
def ask_inputs_single():
    print("=== DeepL Translation Script (modo UN idioma) ===")

    input_path_str = input("Path del archivo de entrada (ej: es.json): ").strip()
    output_path_str = input("Path del archivo de salida (ej: it.json): ").strip()
    target_lang = input("Idioma destino DeepL (ej: FR, PT-BR, DE, ZH): ").strip().upper()

    if not input_path_str:
        raise ValueError("Debe ingresar el path del archivo de entrada.")
    if not output_path_str:
        raise ValueError("Debe ingresar el path del archivo de salida.")
    if not target_lang:
        raise ValueError("Debe ingresar un idioma destino.")

    return Path(input_path_str), Path(output_path_str), target_lang


def ask_inputs_multi():
    print("=== DeepL Translation Script (modo MÚLTIPLES idiomas) ===")

    input_path_str = input("Path del archivo de entrada (ej: es.json): ").strip()
    output_path_str = input("Path del archivo de salida (ej: translations-multi.json): ").strip()
    langs_str = input(
        "Idiomas destino DeepL separados por coma (ej: PT-BR,IT,FR,DE,KO,ZH-HANS): "
    ).strip()

    if not input_path_str:
        raise ValueError("Debe ingresar el path del archivo de entrada.")
    if not output_path_str:
        raise ValueError("Debe ingresar el path del archivo de salida.")
    if not langs_str:
        raise ValueError("Debe ingresar al menos un idioma destino.")

    target_langs = [lang.strip().upper() for lang in langs_str.split(",") if lang.strip()]
    if not target_langs:
        raise ValueError("Lista de idiomas destino vacía luego de procesar.")

    return Path(input_path_str), Path(output_path_str), target_langs


def ask_inputs_default_langs():
    print("=== DeepL Translation Script (modo LENGUAJES POR DEFECTO) ===")
    print("Se usarán automáticamente estos idiomas:")
    print(", ".join(DEFAULT_TARGET_LANGS))

    input_path_str = input("Path del archivo de entrada (ej: es.json): ").strip()
    output_path_str = input(
        "Path del archivo de salida (ej: translations-default.json): "
    ).strip()

    if not input_path_str:
        raise ValueError("Debe ingresar el path del archivo de entrada.")
    if not output_path_str:
        raise ValueError("Debe ingresar el path del archivo de salida.")

    return Path(input_path_str), Path(output_path_str), DEFAULT_TARGET_LANGS


# Traducción por batches
def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    data: dict[str, object] = {
        "auth_key": DEEPL_API_KEY,
        "target_lang": target_lang,
    }

    # DeepL espera muchos parámetros "text"
    for t in texts:
        data.setdefault("text", [])
        # type: ignore[arg-type]  # para mypy opcionalmente
        data["text"].append(t)

    response = requests.post(DEEPL_ENDPOINT, data=data, timeout=60)
    if not response.ok:
        raise RuntimeError(f"DeepL error {response.status_code}: {response.text}")

    payload = response.json()
    translations = payload.get("translations", [])

    if len(translations) != len(texts):
        raise RuntimeError("Mismatch entre textos enviados y traducidos")

    return [t["text"] for t in translations]


# Lógica de traducción para UN idioma (modo viejo)
def translate_single_language(input_path: Path, output_path: Path, target_lang: str) -> None:
    raw = input_path.read_text("utf-8")
    data: dict[str, str] = json.loads(raw)

    items = list(data.items())
    translated: dict[str, str] = {}

    total = len(items)
    print(f"\nTraduciendo {total} entries a {target_lang}...\n")

    for i in range(0, total, BATCH_SIZE):
        batch = items[i : i + BATCH_SIZE]
        keys = [k for k, _ in batch]
        values = [v for _, v in batch]

        try:
            translated_values = translate_batch(values, target_lang)
        except Exception as e:
            print(f"Error traduciendo batch {i}-{i+len(batch)}: {e}")
            time.sleep(5)
            raise

        for k, tv in zip(keys, translated_values, strict=True):
            translated[k] = tv

        print(f"Traducidas {min(i + BATCH_SIZE, total)}/{total}")
        time.sleep(0.5)

    output_path.write_text(
        json.dumps(translated, ensure_ascii=False, indent=2),
        "utf-8",
    )

    print(f"\nListo! Archivo generado: {output_path}\n")


# Nueva lógica: MÚLTIPLES idiomas en un solo archivo
def translate_multiple_languages(input_path: Path, output_path: Path, target_langs: list[str]) -> None:
    raw = input_path.read_text("utf-8")
    data: dict[str, str] = json.loads(raw)
    items = list(data.items())
    total = len(items)

    result: dict[str, dict[str, str]] = {}

    for lang in target_langs:
        print(f"\nTraduciendo {total} entries a {lang}...\n")

        translated_for_lang: dict[str, str] = {}

        for i in range(0, total, BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            keys = [k for k, _ in batch]
            values = [v for _, v in batch]

            try:
                translated_values = translate_batch(values, lang)
            except Exception as e:
                print(f"Error traduciendo batch {i}-{i+len(batch)} para idioma {lang}: {e}")
                time.sleep(5)
                raise

            for k, tv in zip(keys, translated_values, strict=True):
                translated_for_lang[k] = tv

            print(f"[{lang}] Traducidas {min(i + BATCH_SIZE, total)}/{total}")
            time.sleep(0.5)

        result[lang] = translated_for_lang

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"\nListo! Archivo multi-idioma generado: {output_path}\n")


# Main
def main():
    print("=== DeepL Translation Script ===")
    mode = input(
        "Selecciona modo: [1] Un idioma (default) | [2] Múltiples idiomas | [3] Lenguajes por defecto: "
    ).strip()

    if mode == "2":
        # Nuevo modo multi-idioma (idiomas elegidos por el usuario)
        input_path, output_path, target_langs = ask_inputs_multi()
        translate_multiple_languages(input_path, output_path, target_langs)
    elif mode == "3":
        # Modo lenguajes por defecto
        input_path, output_path, target_langs = ask_inputs_default_langs()
        translate_multiple_languages(input_path, output_path, target_langs)
    else:
        # Modo anterior (un solo idioma)
        input_path, output_path, target_lang = ask_inputs_single()
        translate_single_language(input_path, output_path, target_lang)


if __name__ == "__main__":
    main()
