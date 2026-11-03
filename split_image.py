from PIL import Image, ImageDraw
import os


def split_image(filename, output_dir):
    if not os.path.exists(filename):
        print(f"ОШИБКА: Файл {filename} не найден!")
        return

    os.makedirs(output_dir, exist_ok=True)
    img = Image.open(filename).convert("RGBA")

    # 1. Автоматически обрезаем белые/прозрачные поля (находим границы рисунка)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    w, h = img.size

    # 2. Делаем картинку идеально квадратной (чтобы круги не были овалами)
    max_side = max(w, h)
    square_img = Image.new("RGBA", (max_side, max_side), (0, 0, 0, 0))
    square_img.paste(img, ((max_side - w) // 2, (max_side - h) // 2))
    img = square_img
    w, h = img.size

    cx, cy = w // 2, h // 2

    # --- НАСТРОЙКИ РАДИУСОВ (в процентах от размера картинки) ---
    # Если режет "криво" (не по границам колец), просто поменяй эти цифры:
    # Например, если внутренний круг захватывает лишнее, уменьши 0.15 на 0.12
    r_outer = w // 2
    r_mid = int(w * 0.34)  # <--- Средний круг
    r_inner = int(w * 0.18)  # <--- Внутренний круг

    # -----------------------------------------------------------

    def create_masked(radius):
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        # Рисуем ровный круг
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)

        result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)
        return result

    create_masked(r_outer).save(f"{output_dir}/calendar_outer.png")
    create_masked(r_mid).save(f"{output_dir}/calendar_mid.png")
    create_masked(r_inner).save(f"{output_dir}/calendar_center.png")
    print("УСПЕХ! Проверь папку assets.")


split_image("I.png", "assets")