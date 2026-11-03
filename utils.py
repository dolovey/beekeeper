import re
from datetime import datetime

from constants import TIER_SPACING


def open_dialog(page, d):
    if hasattr(page, "show_dialog"):
        page.show_dialog(d)
    else:
        try:
            page.open(d)
            page.update()
        except AttributeError:
            page.dialog = d
            d.open = True
            page.update()

def close_dialog(page, d):
    if hasattr(page, "close_dialog"):
        page.close_dialog(d)
    else:
        try:
            page.close(d)
            page.update()
        except AttributeError:
            d.open = False
            page.update()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return default


def parse_size(size_str):
    if not size_str:
        return 600, 500
    nums = re.findall(r'\d+', str(size_str))
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    elif len(nums) == 1:
        return int(nums[0]), int(nums[0])
    return 600, 500


def parse_event_dt(ev):
    try:
        d = ev.get("date", "")
        t = ev.get("time", "00:00") or "00:00"
        return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def event_applies_to_hive(ev, hid):
    hids = ev.get("hive_ids") or []
    return (not hids) or (hid in hids)


def hex_to_rgb(h):
    try:
        h = h.strip()
        if h.startswith("#") and len(h) == 7:
            return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    except Exception:
        pass
    return 210, 162, 76


def rgb_to_hex(r, g, b):
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def is_dark_color(hex_color):
    r, g, b = hex_to_rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def compute_hive_geometry(h, canvas_w, canvas_h):
    w_mm, h_mm = parse_size(h.get("size"))
    base_scale = 0.25
    w_px = w_mm * base_scale
    main_h_px = h_mm * base_scale
    max_w = canvas_w * 0.8
    if w_px > max_w:
        sc = max_w / w_px
        w_px *= sc
        main_h_px *= sc
    tiers = h.get("tiers") or []
    tier_extra_px = sum((t.get("height", 150) * base_scale) + TIER_SPACING
                        for t in tiers)
    max_total_h = canvas_h * 0.6
    if main_h_px + tier_extra_px > max_total_h:
        sc = max_total_h / (main_h_px + tier_extra_px)
        w_px *= sc
        main_h_px *= sc
        tier_extra_px *= sc
    w_px = max(w_px, 50)
    main_h_px = max(main_h_px, 50)
    total_h = main_h_px + tier_extra_px
    nx = float(h.get("x", 0.5))
    ny = float(h.get("y", 0.4))
    left = clamp(nx * canvas_w, 0, max(canvas_w - w_px, 0))
    top = clamp(ny * canvas_h, 0, max(canvas_h - total_h, 0))
    return left, top, w_px, total_h, main_h_px

def queen_age_years(queen_birth_year):
    """Текущий возраст матки в годах (по году рождения)."""
    if not queen_birth_year:
        return None
    try:
        return max(0, datetime.now().year - int(queen_birth_year))
    except Exception:
        return None


def queen_pin_color(queen_birth_year):
    """Цвет булавки по возрасту матки (пересчитывается каждый год)."""
    age = queen_age_years(queen_birth_year)
    if age is None:
        return "#BDBDBD"   # нет данных — серый
    if age <= 1:
        return "#FFFFFF"   # 1 год — белый
    if age == 2:
        return "#FFEB3B"   # 2 года — жёлтый
    if age == 3:
        return "#F44336"   # 3 года — красный
    return "#4CAF50"       # 4+ лет — зелёный


def queen_pin_border_color(queen_birth_year):
    """Обводка булавки (чтобы белая была видна на светлом фоне)."""
    age = queen_age_years(queen_birth_year)
    if age is None:
        return "#757575"
    if age <= 1:
        return "#212121"
    return "#37474F"

def plural_ru(n, one, few, many):
    """Склонение по числу в русском.
    plural_ru(1, "семья", "семьи", "семей") -> "семья"
    plural_ru(3, "семья", "семьи", "семей") -> "семьи"
    plural_ru(5, "семья", "семьи", "семей") -> "семей"
    """
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many
