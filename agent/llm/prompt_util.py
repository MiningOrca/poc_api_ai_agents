def _render_section_value(value: object) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if isinstance(value, list):
        if not value:
            return []

        lines: list[str] = []
        for item in value:
            if item is None:
                continue

            if isinstance(item, str):
                text = item.strip()
                if text:
                    lines.append(f"- {text}")
                continue

            if isinstance(item, dict):
                if not item:
                    continue

                # Красивый компактный случай для status/description
                if set(item.keys()) >= {"status_code", "description"}:
                    lines.append(f'- {item["status_code"]}: {item["description"]}')
                    continue

                # Обычный dict как многострочный блок
                lines.append("-")
                for key, val in item.items():
                    if isinstance(val, list):
                        if not val:
                            lines.append(f"  {key}: []")
                        else:
                            lines.append(f"  {key}:")
                            for nested in val:
                                lines.append(f"    - {nested}")
                    else:
                        lines.append(f"  {key}: {val}")
                continue

            lines.append(f"- {item}")

        return lines

    if isinstance(value, dict):
        if not value:
            return []

        lines: list[str] = []
        for key, val in value.items():
            if isinstance(val, list):
                if not val:
                    lines.append(f"{key}: []")
                else:
                    lines.append(f"{key}:")
                    for nested in val:
                        lines.append(f"  - {nested}")
            else:
                lines.append(f"{key}: {val}")
        return lines

    return [str(value)]


def add_section(parts: list[str], title: str, value: object) -> None:
    lines = _render_section_value(value)
    if not lines:
        return

    if parts:
        parts.append("")

    parts.append(title)
    parts.extend(lines)