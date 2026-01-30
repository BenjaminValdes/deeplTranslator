import os
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

import deepl

# Tabla destino (según tu Prisma model)
TABLE_NAME = "checklist_item_translations"
ID_COL = "checklist_item_id"

# Locales DB y targets DeepL
TARGETS: List[Tuple[str, str]] = [
    ("es", "ES"),       # base/origen
    ("en", "EN-US"),
    ("pt", "PT-BR"),
    ("it", "IT"),
    ("de", "DE"),
    ("fr", "FR"),
    ("ko", "KO"),
    ("zh", "ZH-HANS"),
]


def sql_escape(value: str) -> str:
    # Postgres: escape de comillas simples duplicándolas
    return value.replace("'", "''")


def parse_values_tuples(sql_fragment: str) -> List[List[Optional[str]]]:
    """
    Parsea tuplas SQL tipo: ('text','Nombre',1,NULL,'x',...)
    Maneja:
      - strings con comillas simples
      - escape de comillas '' dentro de strings
      - NULL
    Devuelve una lista de tuplas, cada una como lista de campos (str o None).
    """
    tuples: List[List[Optional[str]]] = []

    i = 0
    n = len(sql_fragment)

    in_tuple = False
    in_str = False
    current: List[Optional[str]] = []
    token = ""

    while i < n:
        ch = sql_fragment[i]

        if not in_tuple:
            if ch == "(":
                in_tuple = True
                in_str = False
                current = []
                token = ""
            i += 1
            continue

        # Dentro de tupla
        if in_str:
            if ch == "'":
                # escape SQL ''
                if i + 1 < n and sql_fragment[i + 1] == "'":
                    token += "'"
                    i += 2
                    continue
                in_str = False
                i += 1
                continue
            token += ch
            i += 1
            continue

        # No estamos dentro de string
        if ch == "'":
            in_str = True
            i += 1
            continue

        if ch == ",":
            v = token.strip()
            current.append(None if v.upper() == "NULL" else v)
            token = ""
            i += 1
            continue

        if ch == ")":
            v = token.strip()
            current.append(None if v.upper() == "NULL" else v)
            tuples.append(current)
            in_tuple = False
            token = ""
            i += 1
            continue

        token += ch
        i += 1

    return tuples


def extract_values_sections(sql: str) -> List[str]:
    """
    Extrae los fragmentos luego de cada VALUES ... hasta el ';' de cada INSERT.
    Esto evita parsear el '(col1, col2, ...)' del header.
    """
    sections: List[str] = []
    for m in re.finditer(r"\bVALUES\b", sql, flags=re.IGNORECASE):
        start = m.end()
        end = sql.find(";", start)
        if end == -1:
            end = len(sql)
        sections.append(sql[start:end])
    return sections


def translate_text(
    translator: deepl.Translator,
    source_es: str,
    target_deepl: str,
) -> str:
    res = translator.translate_text(source_es, source_lang="ES", target_lang=target_deepl)
    return str(res).strip()


def as_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = str(s).strip()
    return s2 if s2 else None


def main() -> None:
    input_path = Path(input("Path input SQL (ej: checklist_items.sql): ").strip())
    output_path = Path(input("Path output SQL (ej: checklist_item_translations.sql): ").strip())

    api_key = os.getenv("DEEPL_API_KEY") or input("DEEPL_API_KEY (si no está en env): ").strip()
    if not api_key:
        raise ValueError("Falta DEEPL_API_KEY (env o input).")

    sql_text = input_path.read_text("utf-8", errors="strict")
    sections = extract_values_sections(sql_text)

    all_rows: List[List[Optional[str]]] = []
    for sec in sections:
        all_rows.extend(parse_values_tuples(sec))

    if not all_rows:
        raise ValueError("No se detectaron tuplas VALUES en el archivo SQL.")

    translator = deepl.Translator(api_key)

    values_sql: List[str] = []

    # Índices según tu dump:
    # 0 item_type, 1 label, 4 placeholder, 5 description, 11 template_item_id
    IDX_LABEL = 1
    IDX_PLACEHOLDER = 4
    IDX_DESCRIPTION = 5
    IDX_TEMPLATE_ITEM_ID = 11

    for row in all_rows:
        if len(row) <= IDX_TEMPLATE_ITEM_ID:
            # Tupla inesperada, la saltamos
            continue

        checklist_item_id = as_int(row[IDX_TEMPLATE_ITEM_ID])
        base_label_es = normalize(row[IDX_LABEL])
        base_desc_es = normalize(row[IDX_DESCRIPTION])
        base_ph_es = normalize(row[IDX_PLACEHOLDER])

        if checklist_item_id is None:
            continue
        if not base_label_es:
            continue

        # description es requerido en tu model; si viniera vacío, usamos label como fallback
        if not base_desc_es:
            base_desc_es = base_label_es

        for locale_db, deepl_target in TARGETS:
            if locale_db == "es":
                label = base_label_es
                description = base_desc_es
                placeholder = base_ph_es
            else:
                label = translate_text(translator, base_label_es, deepl_target)
                description = translate_text(translator, base_desc_es, deepl_target)
                placeholder = (
                    translate_text(translator, base_ph_es, deepl_target)
                    if base_ph_es
                    else None
                )

            # Armado SQL por fila
            label_sql = f"'{sql_escape(label)}'"
            desc_sql = f"'{sql_escape(description)}'"
            ph_sql = "NULL" if not placeholder else f"'{sql_escape(placeholder)}'"

            values_sql.append(
                f"({checklist_item_id}, '{locale_db}', {label_sql}, {desc_sql}, {ph_sql})"
            )

    if not values_sql:
        raise ValueError("No se generaron filas (¿faltan template_item_id o label?).")

    out_sql = (
        f"INSERT INTO {TABLE_NAME} ({ID_COL}, locale, label, description, placeholder)\n"
        "VALUES\n  "
        + ",\n  ".join(values_sql)
        + f"\nON CONFLICT ({ID_COL}, locale)\n"
          "DO UPDATE SET\n"
          "  label = EXCLUDED.label,\n"
          "  description = EXCLUDED.description,\n"
          "  placeholder = EXCLUDED.placeholder;\n"
    )

    output_path.write_text(out_sql, "utf-8")
    print(f"OK: SQL generado en {output_path} con {len(values_sql)} filas.")


if __name__ == "__main__":
    main()
