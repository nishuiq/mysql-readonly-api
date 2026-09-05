from collections.abc import Sequence

from fastapi import HTTPException


def parse_table_names(table: Sequence[str]) -> list[str]:
    """Support repeated parameters, comma lists, and backtick-quoted literal names."""
    names: list[str] = []
    for item in table:
        i = 0
        while i < len(item):
            if item[i].isspace() or item[i] == ",":
                i += 1
                continue
            if item[i] == "`":
                i += 1
                parts = []
                while i < len(item):
                    if item[i] == "`":
                        i += 1
                        if i < len(item) and item[i] == "`":
                            parts.append("`")
                            i += 1
                            continue
                        break
                    parts.append(item[i])
                    i += 1
                else:
                    raise HTTPException(422, "query.table: unterminated backtick-quoted name.")
                name = "".join(parts)
                while i < len(item) and item[i].isspace():
                    i += 1
                if i < len(item) and item[i] != ",":
                    raise HTTPException(422, "query.table: expected comma after quoted name.")
            else:
                end = item.find(",", i)
                end = len(item) if end < 0 else end
                name = item[i:end].strip()
                i = end
            if name:
                names.append(name)
    return list(dict.fromkeys(names))
