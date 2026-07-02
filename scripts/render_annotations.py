#!/usr/bin/env python3
"""
Render price-action annotations on top of a chart image.

Usage:
  python scripts/render_annotations.py chart.png annotations.json output.png
  python scripts/render_annotations.py chart.png annotations.json output.svg
"""

from __future__ import annotations

import base64
import html
import json
import math
import mimetypes
import struct
import sys
from pathlib import Path
from typing import Any


def image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in (0xD8, 0xD9):
                continue
            length = struct.unpack(">H", data[i : i + 2])[0]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", data[i + 3 : i + 7])
                return width, height
            i += length
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and data[12:16] == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    raise ValueError(f"Unsupported image format or cannot read size: {path}")


def media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "image/png"


def xy(point: list[float] | tuple[float, float], width: int, height: int) -> tuple[float, float]:
    x, y = point
    if abs(x) <= 1 and abs(y) <= 1:
        return x * width, y * height
    return float(x), float(y)


def dim(value: float, total: int) -> float:
    if abs(value) <= 1:
        return value * total
    return float(value)


def clamp(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    return max(low, min(value, high))


def attrs(**kwargs: Any) -> str:
    rendered = []
    for key, value in kwargs.items():
        if value is None:
            continue
        rendered.append(f'{key.replace("_", "-")}="{html.escape(str(value), quote=True)}"')
    return " ".join(rendered)


def estimate_char_width(char: str, size: float) -> float:
    if char.isspace():
        return size * 0.35
    if ord(char) > 127:
        return size
    return size * 0.58


def estimate_text_width(text: str, size: float) -> float:
    return sum(estimate_char_width(char, size) for char in text)


def wrap_line(line: str, size: float, max_width: float) -> list[str]:
    if not line:
        return [""]
    result: list[str] = []
    current = ""
    current_width = 0.0
    for char in line:
        char_width = estimate_char_width(char, size)
        if current and current_width + char_width > max_width:
            result.append(current)
            current = char
            current_width = char_width
        else:
            current += char
            current_width += char_width
    if current:
        result.append(current)
    return result


def layout_text(item: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    size = float(item.get("size", 28))
    padding = float(item.get("padding", max(8, size * 0.32)))
    raw_max_width = item.get("max_width", 0.20)
    max_width = dim(float(raw_max_width), width)
    max_width = clamp(max_width, size * 5, width * 0.45)

    lines: list[str] = []
    for raw_line in str(item.get("text", "")).splitlines() or [""]:
        lines.extend(wrap_line(raw_line, size, max_width))
    max_lines = int(item.get("max_lines", 5))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip("。；，,.;") + "..."

    line_height = float(item.get("line_height", size * 1.18))
    text_width = max((estimate_text_width(line, size) for line in lines), default=0)
    box_width = min(width - 16, text_width + padding * 2)
    box_height = line_height * len(lines) + padding * 2
    x, y = xy(item.get("at", [0, 0]), width, height)
    margin = float(item.get("margin", 10))
    x = clamp(x, margin, width - box_width - margin)
    y = clamp(y, margin, height - box_height - margin)

    return {
        "x": x,
        "y": y,
        "size": size,
        "padding": padding,
        "line_height": line_height,
        "box_width": box_width,
        "box_height": box_height,
        "lines": lines,
    }


def render_text_svg(item: dict[str, Any], width: int, height: int) -> str:
    layout = layout_text(item, width, height)
    x = layout["x"]
    y = layout["y"]
    size = layout["size"]
    padding = layout["padding"]
    line_height = layout["line_height"]
    color = item.get("color", "#ffffff")
    weight = item.get("weight", 650)
    box_enabled = item.get("box", True)
    pieces: list[str] = []

    if "leader_start" in item and "leader_end" in item:
        x1, y1 = xy(item["leader_start"], width, height)
        x2, y2 = xy(item["leader_end"], width, height)
        pieces.append(
            f'<line {attrs(x1=f"{x1:.2f}", y1=f"{y1:.2f}", x2=f"{x2:.2f}", y2=f"{y2:.2f}", stroke=item.get("leader_color", "#6b7280"), stroke_width=item.get("leader_width", 2), opacity=item.get("leader_opacity", 0.78), stroke_linecap="round")}/>'
        )

    if box_enabled:
        box_attrs = attrs(
            x=f"{x:.2f}",
            y=f"{y:.2f}",
            width=f"{layout['box_width']:.2f}",
            height=f"{layout['box_height']:.2f}",
            rx=item.get("radius", 8),
            fill=item.get("box_fill", "#0b0f14"),
            opacity=item.get("box_opacity", 0.72),
        )
        pieces.append(
            f"<rect {box_attrs}/>"
        )

    tspans = []
    text_x = x + padding
    text_y = y + padding + size
    for idx, line in enumerate(layout["lines"]):
        dy = 0 if idx == 0 else line_height
        tspans.append(f'<tspan x="{text_x:.2f}" dy="{dy:.2f}">{html.escape(line)}</tspan>')
    text_attrs = attrs(
        x=f"{text_x:.2f}",
        y=f"{text_y:.2f}",
        fill=color,
        font_size=f"{size:.2f}",
        font_weight=weight,
        font_family="Microsoft YaHei, PingFang SC, Arial, sans-serif",
    )
    pieces.append(f'<text {text_attrs}>{"".join(tspans)}</text>')
    return "\n  ".join(pieces)


def render_shape_svg(item: dict[str, Any], width: int, height: int) -> str:
    typ = item.get("type")
    color = item.get("color", "#111111")
    opacity = item.get("opacity")
    stroke_width = item.get("width", 3)

    if typ == "zone":
        points = [xy(point, width, height) for point in item.get("points", [])]
        points_attr = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        return f'<polygon {attrs(points=points_attr, fill=color, opacity=opacity or 0.18, stroke=item.get("stroke"), stroke_width=item.get("stroke_width"))}/>'

    if typ == "rect":
        x = dim(item.get("x", 0), width)
        y = dim(item.get("y", 0), height)
        w = dim(item.get("w", 0), width)
        h = dim(item.get("h", 0), height)
        return f'<rect {attrs(x=f"{x:.2f}", y=f"{y:.2f}", width=f"{w:.2f}", height=f"{h:.2f}", fill=color, opacity=opacity or 0.22, stroke=item.get("stroke"), stroke_width=item.get("stroke_width"))}/>'

    if typ == "line":
        x1, y1 = xy(item.get("start", [0, 0]), width, height)
        x2, y2 = xy(item.get("end", [0, 0]), width, height)
        return f'<line {attrs(x1=f"{x1:.2f}", y1=f"{y1:.2f}", x2=f"{x2:.2f}", y2=f"{y2:.2f}", stroke=color, stroke_width=stroke_width, stroke_dasharray=item.get("dash"), opacity=opacity, stroke_linecap="round")}/>'

    if typ == "polyline":
        points = [xy(point, width, height) for point in item.get("points", [])]
        points_attr = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        return f'<polyline {attrs(points=points_attr, fill=item.get("fill", "none"), stroke=color, stroke_width=stroke_width, stroke_dasharray=item.get("dash"), opacity=opacity, stroke_linecap="round", stroke_linejoin="round")}/>'

    if typ == "bracket":
        x1, y1 = xy(item.get("start", [0, 0]), width, height)
        x2, y2 = xy(item.get("end", [0, 0]), width, height)
        tick = dim(float(item.get("tick", 0.018)), height)
        direction = -1 if item.get("direction", "up") == "up" else 1
        path = f"M{x1:.2f},{(y1 + direction * tick):.2f} L{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f} L{x2:.2f},{(y2 + direction * tick):.2f}"
        return f'<path {attrs(d=path, fill="none", stroke=color, stroke_width=stroke_width, stroke_dasharray=item.get("dash"), opacity=opacity, stroke_linecap="round", stroke_linejoin="round")}/>'

    if typ == "arrow":
        x1, y1 = xy(item.get("start", [0, 0]), width, height)
        x2, y2 = xy(item.get("end", [0, 0]), width, height)
        return f'<line {attrs(x1=f"{x1:.2f}", y1=f"{y1:.2f}", x2=f"{x2:.2f}", y2=f"{y2:.2f}", stroke=color, stroke_width=stroke_width, opacity=opacity, marker_end="url(#arrowhead)", stroke_linecap="round")}/>'

    if typ == "circle":
        cx, cy = xy(item.get("center", [0, 0]), width, height)
        radius = dim(float(item.get("r", item.get("radius", 0.012))), min(width, height))
        return f'<circle {attrs(cx=f"{cx:.2f}", cy=f"{cy:.2f}", r=f"{radius:.2f}", fill=item.get("fill", "none"), stroke=color, stroke_width=stroke_width, opacity=opacity)}/>'

    if typ == "ellipse":
        cx, cy = xy(item.get("center", [0, 0]), width, height)
        rx = dim(float(item.get("rx", 0.020)), width)
        ry = dim(float(item.get("ry", 0.030)), height)
        return f'<ellipse {attrs(cx=f"{cx:.2f}", cy=f"{cy:.2f}", rx=f"{rx:.2f}", ry=f"{ry:.2f}", fill=item.get("fill", "none"), stroke=color, stroke_width=stroke_width, opacity=opacity)}/>'

    if typ == "marker":
        cx, cy = xy(item.get("center", [0, 0]), width, height)
        radius = dim(float(item.get("r", item.get("radius", 0.012))), min(width, height))
        label = html.escape(str(item.get("label", "")))
        fill = item.get("fill", "#ffffff")
        text_color = item.get("text_color", color)
        size = dim(float(item.get("size", 0.014)), min(width, height))
        return "\n  ".join([
            f'<circle {attrs(cx=f"{cx:.2f}", cy=f"{cy:.2f}", r=f"{radius:.2f}", fill=fill, stroke=color, stroke_width=stroke_width, opacity=opacity)}/>',
            f'<text {attrs(x=f"{cx:.2f}", y=f"{(cy + size * 0.35):.2f}", fill=text_color, font_size=f"{size:.2f}", font_weight=item.get("weight", 700), text_anchor="middle", font_family="Microsoft YaHei, PingFang SC, Arial, sans-serif")}>{label}</text>',
        ])

    raise ValueError(f"Unsupported annotation type: {typ}")


def render_svg(chart_path: Path, annotations_path: Path) -> str:
    width, height = image_size(chart_path)
    encoded = base64.b64encode(chart_path.read_bytes()).decode("ascii")
    payload = json.loads(annotations_path.read_text(encoding="utf-8"))
    items = payload.get("annotations", [])
    shape_items = [item for item in items if item.get("type") != "text"]
    text_items = [item for item in items if item.get("type") == "text"]
    body = "\n  ".join(
        [render_shape_svg(item, width, height) for item in shape_items]
        + [render_text_svg(item, width, height) for item in text_items]
    )
    mime = media_type(chart_path)
    title = html.escape(str(payload.get("title", "Price Action Analysis")))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <title>{title}</title>
  <defs>
    <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="context-stroke"/>
    </marker>
  </defs>
  <image href="data:{mime};base64,{encoded}" x="0" y="0" width="{width}" height="{height}"/>
  {body}
</svg>
'''


def hex_to_rgba(color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return (
        int(color[0:2], 16),
        int(color[2:4], 16),
        int(color[4:6], 16),
        int(clamp(opacity, 0, 1) * 255),
    )


def load_font(size: int) -> Any:
    from PIL import ImageFont

    for path in [
        # Windows
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial.ttf",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_dashed_line(draw: Any, start: tuple[float, float], end: tuple[float, float], fill: tuple[int, int, int, int], width: int, dash: tuple[int, int] = (16, 10)) -> None:
    x1, y1 = start
    x2, y2 = end
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance == 0:
        return
    dx = (x2 - x1) / distance
    dy = (y2 - y1) / distance
    pos = 0.0
    while pos < distance:
        seg = min(dash[0], distance - pos)
        draw.line((x1 + dx * pos, y1 + dy * pos, x1 + dx * (pos + seg), y1 + dy * (pos + seg)), fill=fill, width=width)
        pos += dash[0] + dash[1]


def draw_arrow(draw: Any, start: tuple[float, float], end: tuple[float, float], fill: tuple[int, int, int, int], width: int) -> None:
    draw.line((*start, *end), fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    angle = math.atan2(y2 - y1, x2 - x1)
    size = max(12, width * 4)
    points = [
        (x2, y2),
        (x2 - size * math.cos(angle - math.pi / 6), y2 - size * math.sin(angle - math.pi / 6)),
        (x2 - size * math.cos(angle + math.pi / 6), y2 - size * math.sin(angle + math.pi / 6)),
    ]
    draw.polygon(points, fill=fill)


def render_png(chart_path: Path, annotations_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("PNG output requires Pillow. Install it with: python -m pip install Pillow") from exc

    image = Image.open(chart_path).convert("RGBA")
    width, height = image.size
    payload = json.loads(annotations_path.read_text(encoding="utf-8"))
    items = payload.get("annotations", [])
    shape_items = [item for item in items if item.get("type") != "text"]
    text_items = [item for item in items if item.get("type") == "text"]
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for item in shape_items:
        typ = item.get("type")
        color = item.get("color", "#111111")
        opacity = float(item.get("opacity", 0.95 if typ in {"line", "arrow"} else 0.22))
        fill = hex_to_rgba(color, opacity)
        stroke_width = int(item.get("width", 3))
        if typ == "zone":
            draw.polygon([xy(point, width, height) for point in item.get("points", [])], fill=fill)
        elif typ == "rect":
            x = dim(item.get("x", 0), width)
            y = dim(item.get("y", 0), height)
            w = dim(item.get("w", 0), width)
            h = dim(item.get("h", 0), height)
            draw.rectangle((x, y, x + w, y + h), fill=fill)
        elif typ == "line":
            start = xy(item.get("start", [0, 0]), width, height)
            end = xy(item.get("end", [0, 0]), width, height)
            if item.get("dash"):
                draw_dashed_line(draw, start, end, fill, stroke_width)
            else:
                draw.line((*start, *end), fill=fill, width=stroke_width)
        elif typ == "polyline":
            points = [xy(point, width, height) for point in item.get("points", [])]
            if len(points) >= 2:
                if item.get("dash"):
                    for start, end in zip(points, points[1:]):
                        draw_dashed_line(draw, start, end, fill, stroke_width)
                else:
                    draw.line(points, fill=fill, width=stroke_width, joint="curve")
        elif typ == "bracket":
            x1, y1 = xy(item.get("start", [0, 0]), width, height)
            x2, y2 = xy(item.get("end", [0, 0]), width, height)
            tick = dim(float(item.get("tick", 0.018)), height)
            direction = -1 if item.get("direction", "up") == "up" else 1
            points = [(x1, y1 + direction * tick), (x1, y1), (x2, y2), (x2, y2 + direction * tick)]
            if item.get("dash"):
                for start, end in zip(points, points[1:]):
                    draw_dashed_line(draw, start, end, fill, stroke_width)
            else:
                draw.line(points, fill=fill, width=stroke_width, joint="curve")
        elif typ == "arrow":
            draw_arrow(draw, xy(item.get("start", [0, 0]), width, height), xy(item.get("end", [0, 0]), width, height), fill, stroke_width)
        elif typ == "circle":
            cx, cy = xy(item.get("center", [0, 0]), width, height)
            radius = dim(float(item.get("r", item.get("radius", 0.012))), min(width, height))
            fill_color = item.get("fill")
            fill_rgba = None if fill_color in (None, "none") else hex_to_rgba(fill_color, float(item.get("fill_opacity", opacity)))
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=fill, width=stroke_width, fill=fill_rgba)
        elif typ == "ellipse":
            cx, cy = xy(item.get("center", [0, 0]), width, height)
            rx = dim(float(item.get("rx", 0.020)), width)
            ry = dim(float(item.get("ry", 0.030)), height)
            fill_color = item.get("fill")
            fill_rgba = None if fill_color in (None, "none") else hex_to_rgba(fill_color, float(item.get("fill_opacity", opacity)))
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=fill, width=stroke_width, fill=fill_rgba)
        elif typ == "marker":
            cx, cy = xy(item.get("center", [0, 0]), width, height)
            radius = dim(float(item.get("r", item.get("radius", 0.012))), min(width, height))
            marker_fill = hex_to_rgba(item.get("fill", "#ffffff"), float(item.get("fill_opacity", 0.92)))
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=fill, width=stroke_width, fill=marker_fill)
            label = str(item.get("label", ""))
            marker_font_size = int(dim(float(item.get("size", 0.014)), min(width, height)))
            font = load_font(marker_font_size)
            text_fill = hex_to_rgba(item.get("text_color", color), 1.0)
            try:
                bbox = draw.textbbox((0, 0), label, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            except AttributeError:
                text_width, text_height = draw.textsize(label, font=font)
            draw.text((cx - text_width / 2, cy - text_height / 2), label, font=font, fill=text_fill)
        else:
            raise ValueError(f"Unsupported annotation type: {typ}")

    for item in text_items:
        layout = layout_text(item, width, height)
        x = layout["x"]
        y = layout["y"]
        size = int(layout["size"])
        padding = layout["padding"]
        line_height = layout["line_height"]
        if "leader_start" in item and "leader_end" in item:
            leader_fill = hex_to_rgba(item.get("leader_color", "#6b7280"), float(item.get("leader_opacity", 0.78)))
            leader_width = int(item.get("leader_width", 2))
            draw.line((*xy(item["leader_start"], width, height), *xy(item["leader_end"], width, height)), fill=leader_fill, width=leader_width)
        if item.get("box", True):
            radius = int(item.get("radius", 8))
            box_fill = hex_to_rgba(item.get("box_fill", "#0b0f14"), float(item.get("box_opacity", 0.72)))
            draw.rounded_rectangle((x, y, x + layout["box_width"], y + layout["box_height"]), radius=radius, fill=box_fill)
        font = load_font(size)
        text_x = x + padding
        text_y = y + padding
        text_fill = hex_to_rgba(item.get("color", "#ffffff"), 1.0)
        for line in layout["lines"]:
            draw.text((text_x, text_y), line, font=font, fill=text_fill)
            text_y += line_height

    result = Image.alpha_composite(image, overlay).convert("RGB")
    result.save(output_path)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: render_annotations.py <chart-image> <annotations.json> <output.png|output.svg>", file=sys.stderr)
        return 2
    chart_path = Path(argv[1])
    annotations_path = Path(argv[2])
    output_path = Path(argv[3])
    suffix = output_path.suffix.lower()
    if suffix == ".svg":
        output_path.write_text(render_svg(chart_path, annotations_path), encoding="utf-8")
    elif suffix == ".png":
        render_png(chart_path, annotations_path, output_path)
    else:
        print("Output must end with .png or .svg", file=sys.stderr)
        return 2
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
