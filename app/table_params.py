"""解析 DDL 请求中的重复参数和带引用的对象名称"""

from collections.abc import Sequence

from fastapi import HTTPException


def parse_table_names(table: Sequence[str]) -> list[str]:
    """解析并按首次出现顺序去重对象名称

    Args:
        table: 重复的 table 参数，支持逗号列表及反引号引用，双反引号表示名称内的反引号

    Returns:
        去重后的名称列表，空白参数被忽略，可返回空列表

    Raises:
        HTTPException: 反引号未闭合或引用名称后存在无效字符，状态为 422
    """
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
