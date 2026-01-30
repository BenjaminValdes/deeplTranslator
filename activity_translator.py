import json
import os
import time
from pathlib import Path
from typing import Any, Iterable
import requests
from dotenv import load_dotenv


load_dotenv()

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
if not DEEPL_API_KEY:
    raise SystemExit("Missing DEEPL_API_KEY env var")

DEEPL_ENDPOINT = "https://api.deepl.com/v2/translate"
BATCH_SIZE = 50

DEFAULT_TARGET_LANGS = ["EN", "PT-BR", "IT", "DE", "FR", "KO", "ZH-HANS"]


def ask_mode() -> str:
    print("=== DeepL Translation Script (JSON list-of-objects) ===")
    print("Modos:")
    print("  [1] Un idioma")
    print("  [2] Múltiples idiomas")
    print("  [3] Idiomas por defecto")
    mode = input("Selecciona modo [1/2/3]: ").strip()
    return mode or "1"


def ask_common_inputs():
    input_path_str = input("Path del archivo de entrada (ej: activity_types.es.json): ").strip()
    output_path_str = input("Path del archivo de salida (ej: activity_types.out.json): ").strip()

    if not input_path_str:
        raise ValueError("Debe ingresar el path del archivo de entrada.")
    if not output_path_str:
        raise ValueError("Debe ingresar el path del archivo de salida.")

    root_key = input('Root key opcional (ej: activity_types). Enter para auto-detectar: ').strip() or None

    fields_str = input(
        "Campos a traducir separados por coma (ej: name,description). Default: name: "
    ).strip()
    fields = [f.strip() for f in (fields_str.split(",") if fields_str else ["name"]) if f.strip()]
    if not fields:
        raise ValueError("Debe indicar al menos un campo a traducir (ej: name).")

    print("\nEstrategia de salida:")
    print("  [1] Crear campos por idioma (ej: name_en, name_fr) (recomendado)")
    print("  [2] Sobrescribir el/los campos originales (ej: name) (peligroso)")
    output_mode = input("Selecciona [1/2] (default 1): ").strip() or "1"
    if output_mode not in ("1", "2"):
        output_mode = "1"

    return Path(input_path_str), Path(output_path_str), root_key, fields, output_mode


def ask_target_langs(mode: str) -> list[str]:
    if mode == "2":
        langs_str = input("Idiomas destino (coma) (ej: PT-BR,IT,FR,DE,KO,ZH-HANS): ").strip()
        if not langs_str:
            raise ValueError("Debe ingresar al menos un idioma destino.")
        langs = [l.strip().upper() for l in langs_str.split(",") if l.strip()]
        if not langs:
            raise ValueError("Lista de idiomas destino vacía luego de procesar.")
        return langs

    if mode == "3":
        print("Se usarán automáticamente estos idiomas:")
        print(", ".join(DEFAULT_TARGET_LANGS))
        return DEFAULT_TARGET_LANGS

    target = input("Idioma destino DeepL (ej: FR, PT-BR, DE, ZH-HANS): ").strip().upper()
    if not target:
        raise ValueError("Debe ingresar un idioma destino.")
    return [target]


def deepl_lang_to_suffix(lang: str) -> str:
    # Para generar name_en, name_pt_br, etc.
    s = lang.lower().replace("-", "_")
    # Opcional: abreviar zh-hans -> zh
    # si prefieres zh_hans, comenta el if
    if s == "zh_hans":
        return "zh"
    return s


def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    data: dict[str, Any] = {
        "auth_key": DEEPL_API_KEY,
        "target_lang": target_lang,
    }
    data["text"] = texts

    resp = requests.post(DEEPL_ENDPOINT, data=data, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"DeepL error {resp.status_code}: {resp.text}")

    payload = resp.json()
    translations = payload.get("translations", [])
    if len(translations) != len(texts):
        raise RuntimeError("Mismatch entre textos enviados y traducidos")

    return [t["text"] for t in translations]


def with_retries(fn, *, max_attempts: int = 4, base_sleep: float = 2.0):
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt == max_attempts:
                break
            sleep_s = base_sleep * attempt
            print(f"Error (attempt {attempt}/{max_attempts}): {e}. Reintentando en {sleep_s:.1f}s...")
            time.sleep(sleep_s)
    raise last_err  # type: ignore[misc]


def load_objects(input_path: Path, root_key: str | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    raw = input_path.read_text("utf-8")
    data = json.loads(raw)

    # Caso A: raíz es lista
    if isinstance(data, list):
        objs = data
        if not all(isinstance(x, dict) for x in objs):
            raise ValueError("El JSON raíz es una lista pero no todos los items son objetos.")
        return objs, None, None

    # Caso B: raíz es dict
    if not isinstance(data, dict):
        raise ValueError("JSON inválido: se esperaba dict o list en la raíz.")

    if root_key:
        if root_key not in data or not isinstance(data[root_key], list):
            raise ValueError(f'Root key "{root_key}" no existe o no contiene una lista.')
        objs = data[root_key]
        if not all(isinstance(x, dict) for x in objs):
            raise ValueError(f'Root key "{root_key}" no contiene objetos (dict).')
        return objs, data, root_key

    # Auto-detect: si hay exactamente una key cuyo valor es lista de dicts, usarla
    candidate_keys = []
    for k, v in data.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            candidate_keys.append(k)

    if len(candidate_keys) == 1:
        k = candidate_keys[0]
        return data[k], data, k

    # Si no se puede detectar, intentar si alguna key tiene lista (aunque vacía)
    for k, v in data.items():
        if isinstance(v, list):
            # si está vacía, aceptamos igual
            if not v or all(isinstance(x, dict) for x in v):
                return v, data, k

    raise ValueError(
        "No se pudo auto-detectar la lista de objetos. Indica root_key (ej: activity_types)."
    )


def collect_texts(objs: list[dict[str, Any]], fields: list[str]) -> tuple[list[tuple[int, str]], list[str]]:
    """
    Devuelve:
      - positions: [(obj_index, field_name), ...] para mapear de vuelta
      - texts:     [text, ...]
    """
    positions: list[tuple[int, str]] = []
    texts: list[str] = []

    for idx, obj in enumerate(objs):
        for f in fields:
            v = obj.get(f, None)
            if isinstance(v, str):
                s = v.strip()
                if s:
                    positions.append((idx, f))
                    texts.append(s)
            # si no es str, se ignora (IDs, nulls, etc.)

    return positions, texts


def apply_translations(
    objs: list[dict[str, Any]],
    positions: list[tuple[int, str]],
    translated_texts: list[str],
    *,
    lang: str,
    fields: list[str],
    output_mode: str,
):
    suffix = deepl_lang_to_suffix(lang)

    for (idx, field_name), t in zip(positions, translated_texts, strict=True):
        if output_mode == "2":
            # overwrite
            objs[idx][field_name] = t
        else:
            # create new per-language field, e.g. name_en
            new_key = f"{field_name}_{suffix}"
            objs[idx][new_key] = t


def translate_objects_file(
    input_path: Path,
    output_path: Path,
    root_key: str | None,
    fields: list[str],
    target_langs: list[str],
    output_mode: str,
):
    objs, root_container, used_root_key = load_objects(input_path, root_key)

    positions, texts = collect_texts(objs, fields)
    total = len(texts)
    print(f"\nTotal textos a traducir: {total} (campos: {', '.join(fields)})")

    if total == 0:
        print("No hay textos no vacíos para traducir. Se copiará el JSON sin cambios.")
        # escribir tal cual
        if root_container is None:
            output_path.write_text(json.dumps(objs, ensure_ascii=False, indent=2), "utf-8")
        else:
            root_container[used_root_key] = objs
            output_path.write_text(json.dumps(root_container, ensure_ascii=False, indent=2), "utf-8")
        print(f"Listo! Archivo generado: {output_path}")
        return

    for lang in target_langs:
        print(f"\nTraduciendo a {lang}...")

        translated_all: list[str] = []
        for i in range(0, total, BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]

            def do_call():
                return translate_batch(batch, lang)

            translated_batch = with_retries(do_call)
            translated_all.extend(translated_batch)

            print(f"[{lang}] {min(i + BATCH_SIZE, total)}/{total}")
            time.sleep(0.5)

        apply_translations(
            objs,
            positions,
            translated_all,
            lang=lang,
            fields=fields,
            output_mode=output_mode,
        )

    # Guardar respetando el formato original
    if root_container is None:
        out_data: Any = objs
    else:
        root_container[used_root_key] = objs
        out_data = root_container

    output_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nListo! Archivo generado: {output_path}\n")


def main():
    mode = ask_mode()
    input_path, output_path, root_key, fields, output_mode = ask_common_inputs()
    target_langs = ask_target_langs(mode)

    translate_objects_file(
        input_path=input_path,
        output_path=output_path,
        root_key=root_key,
        fields=fields,
        target_langs=target_langs,
        output_mode=output_mode,
    )


if __name__ == "__main__":
    main()
