import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import deepl

ROOT_KEY = "subgroups"

# Tu tabla destino
TABLE_NAME = "subgroup_translations"
ID_COL = "subgroup_id"
TEXT_COL = "subgroup_name"

# 8 idiomas como en tu app (locales DB) y targets DeepL
TARGETS: List[Tuple[str, str]] = [
    ("es", "ES"),       # origen/base
    ("en", "EN-US"),    # o "EN-GB" si preferís
    ("pt", "PT-BR"),
    ("it", "IT"),
    ("de", "DE"),
    ("fr", "FR"),
    ("ko", "KO"),
    ("zh", "ZH-HANS"),
]

def sql_escape(value: str) -> str:
    return value.replace("'", "''")

def read_rows(input_path: Path) -> List[Dict[str, Any]]:
    data: Any = json.loads(input_path.read_text("utf-8"))
    rows = data.get(ROOT_KEY, []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"No se encontró una lista bajo '{ROOT_KEY}' en el JSON.")
    return [r for r in rows if isinstance(r, dict)]

def translate_all(
    translator: deepl.Translator,
    source_es: str,
    target_deepl: str,
) -> str:
    # DeepL requiere source_lang para resultados consistentes
    res = translator.translate_text(source_es, source_lang="ES", target_lang=target_deepl)
    return str(res).strip()

def main():
    input_path = Path(input("Path input JSON (ej: subgroups.json): ").strip())
    output_path = Path(input("Path output SQL (ej: subgroup_translations.sql): ").strip())

    api_key = os.getenv("DEEPL_API_KEY") or input("DEEPL_API_KEY (si no está en env): ").strip()
    if not api_key:
        raise ValueError("Falta DEEPL_API_KEY (env o input).")

    translator = deepl.Translator(api_key)

    rows = read_rows(input_path)

    values_sql: List[str] = []

    for obj in rows:
        subgroup_id = obj.get("subgroup_id")
        base_es = obj.get("subgroup_name")

        if not isinstance(subgroup_id, int):
            continue
        if not isinstance(base_es, str) or not base_es.strip():
            continue

        base_es = base_es.strip()

        for locale_db, deepl_target in TARGETS:
            if locale_db == "es":
                text = base_es
            else:
                text = translate_all(translator, base_es, deepl_target)

            if text:
                values_sql.append(
                    f"({subgroup_id}, '{locale_db}', '{sql_escape(text)}')"
                )

    if not values_sql:
        raise ValueError("No se generaron filas (¿faltan subgroup_name o subgroup_id?).")

    sql = (
        f"INSERT INTO {TABLE_NAME} ({ID_COL}, locale, {TEXT_COL})\n"
        "VALUES\n  "
        + ",\n  ".join(values_sql)
        + f"\nON CONFLICT ({ID_COL}, locale)\n"
          f"DO UPDATE SET {TEXT_COL} = EXCLUDED.{TEXT_COL};\n"
    )

    output_path.write_text(sql, "utf-8")
    print(f"OK: SQL generado en {output_path} con {len(values_sql)} filas.")

if __name__ == "__main__":
    main()
