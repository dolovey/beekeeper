import flet as ft
import calendar
import math
import threading
import webbrowser
import os
import zipfile
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from constants import (
    HONEY, SOFT_YELLOW, DANGER, WOOD_DARK, WOOD_LIGHT, ENTRANCE,
    SCALE_DEFAULT_COLOR, MONTHS_RU, MONTHS_SHORT, MONTH_DEGREES,
    TEMPLATES, TIER_SPACING,
)
from utils import (
    clamp, safe_int, safe_float,
    parse_event_dt, event_applies_to_hive,
    hex_to_rgb, rgb_to_hex, is_dark_color, compute_hive_geometry,
    queen_age_years, queen_pin_color, queen_pin_border_color,
    plural_ru,
)
from storage import Storage
from previews import mini_hive_preview, mini_tier_preview
from charts import make_weight_chart
from notifications import notification_loop

Icons = getattr(ft, "Icons", None) or getattr(ft, "icons", None)


def main(page: ft.Page):
    page.title = "Пчеловод"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 12
    page.bgcolor = "#FFFFFF"

    storage = Storage()
    body = ft.Column(expand=True, spacing=12)
    page.add(body)

    current_aid = None
    current_hid = None
    pending_photo = {"aid": None, "hid": None, "tid": None}

    # --- Инициализация сервисов для Flet 1.0 ---
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    date_picker = ft.DatePicker(first_date=datetime(2020, 1, 1), last_date=datetime(2035, 12, 31))
    page.services.append(date_picker)
    date_cb = {"fn": None}

    time_picker = ft.TimePicker()
    page.services.append(time_picker)
    time_cb = {"fn": None}

    cal_state = {
        "year": datetime.now().year,
        "month": datetime.now().month,
        "selected": datetime.now().strftime("%Y-%m-%d"),
    }

    # ================= ХЕЛПЕРЫ ДЛЯ ДИАЛОГОВ (Flet 1.0) =================
    def open_dialog(dlg):
        page.show_dialog(dlg)

    def close_dialog(dlg):
        page.close_dialog(dlg)

    def confirm_action(title, message, on_confirm):
        def yes(e):
            close_dialog(dlg)
            on_confirm()

        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dlg)),
                ft.Button("Применить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=yes),
            ])
        open_dialog(dlg)

    # ================= PICKERS =================
    def open_date_picker(on_pick):
        date_cb["fn"] = on_pick
        page.open(date_picker)

    def handle_date_change(e):
        v = date_picker.value
        if not v: return
        if not isinstance(v, str): v = v.strftime("%Y-%m-%d")
        cb = date_cb["fn"]
        if cb: cb(v)
        page.close(date_picker)

    date_picker.on_change = handle_date_change

    def open_time_picker(on_pick):
        time_cb["fn"] = on_pick
        page.open(time_picker)

    def handle_time_change(e):
        v = time_picker.value
        if not v: return
        if hasattr(v, "strftime"): s = v.strftime("%H:%M")
        else:
            s = str(v)
            if len(s) > 5: s = s[:5]
        cb = time_cb["fn"]
        if cb: cb(s)
        page.close(time_picker)

    time_picker.on_change = handle_time_change

    def copy_to_clipboard(text):
        try:
            page.run_task(page.set_clipboard, text)
        except Exception as ex:
            print(f"copy error: {ex}")

    # ================= NOTIFICATIONS =================
    threading.Thread(target=notification_loop, args=(storage,), daemon=True).start()

    # ================= PHOTOS =================
    async def pick_photo(e, aid, hid):
        files = await file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
        if not files: return
        storage.save_photo(aid, hid, files[0].path)
        if current_hid == hid and current_aid == aid: show_hive_detail(aid, hid)
        elif current_aid == aid: show_apiary(aid)

    async def pick_tier_photo(e, aid, hid, tid):
        files = await file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
        if not files: return
        storage.save_tier_photo(aid, hid, tid, files[0].path)
        if current_hid == hid and current_aid == aid: show_hive_detail(aid, hid)
        elif current_aid == aid: show_apiary(aid)

    def clear_main_photo(aid, hid):
        storage.clear_photo(aid, hid)
        if current_hid == hid: show_hive_detail(aid, hid)
        else: show_apiary(aid)

    def clear_tier_photo(aid, hid, tid):
        storage.clear_tier_photo(aid, hid, tid)
        if current_hid == hid: show_hive_detail(aid, hid)
        else: show_apiary(aid)

    # ================= BACKUP / RESTORE =================
    async def export_backup(e):
        try:
            backup_dir = Path(page.get_downloads_directory())
            save_path = backup_dir / f"beekeeper_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(storage.data_root):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, storage.data_root)
                        zipf.write(file_path, arcname)
            
            page.show_dialog(ft.SnackBar(ft.Text(f"Бэкап сохранен в Загрузки!")))
        except Exception as ex:
            page.show_dialog(ft.SnackBar(ft.Text(f"Ошибка бэкапа: {ex}")))

    async def import_backup(e):
        try:
            files = await file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"])
            if not files: return
            zip_path = files[0].path
            
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(storage.data_root)
            
            page.show_dialog(ft.SnackBar(ft.Text("Данные успешно восстановлены!")))
            show_welcome()
        except Exception as ex:
            page.show_dialog(ft.SnackBar(ft.Text(f"Ошибка восстановления: {ex}")))

    # ================= WELCOME =================
    def show_welcome():
        nonlocal current_aid, current_hid
        current_aid = None
        current_hid = None
        page.bgcolor = "#FFFFFF"
        body.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        body.controls.clear()

        body.controls.append(ft.Container(height=12))
        body.controls.append(ft.Text("Пасека", size=36, weight=ft.FontWeight.BOLD, color=HONEY, text_align=ft.TextAlign.CENTER))
        body.controls.append(ft.Text("Выберите пасеку", size=16, color="#666666", text_align=ft.TextAlign.CENTER))
        body.controls.append(ft.Container(height=12))

        apiaries = storage.list_apiaries()
        if not apiaries:
            body.controls.append(ft.Text("У вас пока нет пасек", text_align=ft.TextAlign.CENTER))
            body.controls.append(ft.Button("Создать пасеку", icon=Icons.ADD, style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=lambda e: open_create_apiary()))
        else:
            for a in apiaries:
                count = len(storage.list_hives(a["id"]))
                hive_word = plural_ru(count, "улей", "улья", "ульев")
                body.controls.append(ft.Card(content=ft.Container(
                    content=ft.ListTile(
                        leading=ft.Icon(Icons.HOME, color=HONEY),
                        title=ft.Text(a["name"], size=18, weight=ft.FontWeight.W_500),
                        subtitle=ft.Text(f"{count} {hive_word}"),
                        trailing=ft.Icon(Icons.CHEVRON_RIGHT)),
                    on_click=lambda e, aid=a["id"]: show_apiary(aid), ink=True)))
            body.controls.append(ft.Container(height=8))
            body.controls.append(ft.OutlinedButton("Создать пасеку", icon=Icons.ADD, on_click=lambda e: open_create_apiary()))

        body.controls.append(ft.Container(height=20))
        body.controls.append(ft.Row([
            ft.Button("📤 Резервная копия", on_click=export_backup, style=ft.ButtonStyle(bgcolor="#E0E0E0", color="#333333")),
            ft.Button("📥 Восстановить", on_click=import_backup, style=ft.ButtonStyle(bgcolor="#E0E0E0", color="#333333")),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=10))

        page.update()

    # ================= APIARY (canvas) =================
    def show_apiary(aid):
        nonlocal current_aid, current_hid
        current_aid = aid
        current_hid = None
        apiary = storage.get_apiary(aid)
        if not apiary: return show_welcome()

        page.bgcolor = SOFT_YELLOW
        body.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        body.controls.clear()

        body.controls.append(ft.Row([
            ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: show_welcome()),
            ft.Text(apiary["name"], size=20, weight=ft.FontWeight.BOLD, expand=True),
            ft.IconButton(Icons.MENU_BOOK, icon_color=HONEY, icon_size=28, tooltip="Книга пчеловода", on_click=lambda e: show_beekeeper_book(aid)),
            ft.IconButton(Icons.CALENDAR_MONTH, icon_color=HONEY, icon_size=28, tooltip="Календарь", on_click=lambda e: show_calendar(aid)),
            ft.IconButton(Icons.ADD_CIRCLE, icon_color=HONEY, icon_size=36, tooltip="Добавить", on_click=lambda e: open_add_menu(aid)),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        canvas_w = max(int(page.width or 400) - 24, 280)
        canvas_h = max(int(page.height or 600) - 130, 320)

        stack = ft.Stack(expand=True)
        hives = storage.list_hives(aid)
        scales = storage.list_scales(aid)

        if not hives and not scales:
            stack.controls.append(ft.Container(
                left=0, top=0, width=canvas_w, height=canvas_h, alignment=ft.alignment.center,
                content=ft.Column([
                    ft.Icon(Icons.WIDGETS, size=64, color=HONEY),
                    ft.Text("Здесь пока пусто", size=18, text_align=ft.TextAlign.CENTER),
                    ft.Text("Нажмите «+» в правом верхнем углу.\nУльи и весы можно перетаскивать.", color="#666666", text_align=ft.TextAlign.CENTER),
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)))
            body.controls.append(ft.Container(expand=True, bgcolor=SOFT_YELLOW, border_radius=12, content=stack))
            page.update()
            return

        hive_ids = {h["id"] for h in hives}
        attached_map = {}
        free_scales = []
        for s in scales:
            ahid = s.get("attached_hive_id")
            if ahid and ahid in hive_ids: attached_map.setdefault(ahid, []).append(s)
            else: free_scales.append(s)

        for h in hives:
            c = build_hive_on_canvas(aid, h, canvas_w, canvas_h, attached_map.get(h["id"], []), hives)
            stack.controls.append(c)

        for s in free_scales:
            c = build_scale_on_canvas(aid, s, canvas_w, canvas_h, hives)
            stack.controls.append(c)

        body.controls.append(ft.Container(expand=True, bgcolor=SOFT_YELLOW, border_radius=12, content=stack))
        page.update()

    # ================= BEEKEEPER BOOK =================
    def show_beekeeper_book(aid):
        nonlocal current_aid, current_hid
        current_aid = aid
        current_hid = None
        apiary = storage.get_apiary(aid)
        if not apiary: return show_welcome()

        page.bgcolor = "#FFFFFF"
        body.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        body.controls.clear()

        body.controls.append(ft.Row([
            ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: show_apiary(aid)),
            ft.Text(f"📖 {apiary['name']}", size=22, weight=ft.FontWeight.BOLD, expand=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        hives = storage.list_hives(aid)
        scales = storage.list_scales(aid)
        events = storage.list_events(aid)
        today_str = datetime.now().strftime("%Y-%m-%d")

        hive_measurements = {}
        for s in scales:
            for m in s.get("measurements") or []:
                hid_m = m.get("hive_id")
                if hid_m: hive_measurements.setdefault(hid_m, []).append(m)

        book_col = ft.Column([], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

        if not hives:
            book_col.controls.append(ft.Container(
                padding=40, alignment=ft.alignment.center,
                content=ft.Column([
                    ft.Icon(Icons.MENU_BOOK, size=64, color="#CCCCCC"),
                    ft.Text("Пока нет ульев на пасеке", size=16, color="#666666", text_align=ft.TextAlign.CENTER),
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)))
        else:
            for h in hives:
                book_col.controls.append(build_book_hive_card(aid, h, hive_measurements, events, today_str))

        body.controls.append(book_col)
        page.update()

    def build_book_families_block(aid, hid, hive):
        families = hive.get("families_data") or []
        content_holder = ft.Container(visible=False)
        arrow_ref = {"icon": ft.Icon(Icons.ARROW_DROP_DOWN, color=HONEY, size=20)}

        def toggle(e):
            content_holder.visible = not content_holder.visible
            arrow_ref["icon"].name = (Icons.ARROW_DROP_UP if content_holder.visible else Icons.ARROW_DROP_DOWN)
            page.update()

        header = ft.Container(
            on_click=toggle, ink=True, padding=6, border_radius=6,
            content=ft.Row([
                ft.Text(f"🐝 Семьи ({len(families)})", size=13, weight=ft.FontWeight.BOLD, expand=True),
                ft.Container(content=arrow_ref["icon"]),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER))

        if families:
            items = []
            for i, f in enumerate(families):
                age = queen_age_years(f.get("queen_birth_year"))
                age_text = f"{age} {plural_ru(age, 'год', 'года', 'лет')}" if age is not None else "—"
                pin_color = queen_pin_color(f.get("queen_birth_year"))
                pin_border = queen_pin_border_color(f.get("queen_birth_year"))

                row_items = [
                    ft.Row([
                        ft.Container(width=14, height=14, shape=ft.BoxShape.CIRCLE, bgcolor=pin_color, border=ft.border.all(1.5, pin_border)),
                        ft.Text(f"Семья {i + 1} · матка {age_text}", size=12, weight=ft.FontWeight.BOLD, expand=True),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ]
                if f.get("state"): row_items.append(ft.Text(f"Состояние: {f.get('state')}", size=11, color="#555555"))
                if f.get("notes"): row_items.append(ft.Text(f.get("notes"), size=11, color="#666666", italic=True))

                items.append(ft.Container(
                    padding=8, margin=ft.margin.only(left=16), bgcolor="#FFFFFF", border_radius=6, border=ft.border.all(1, "#E0E0E0"),
                    content=ft.Column(row_items, spacing=3)))

            content_holder.content = ft.Column(items, spacing=6)
        else:
            content_holder.content = ft.Container(padding=8, margin=ft.margin.only(left=16), content=ft.Text("В улье пока нет семей", size=11, color="#999999", italic=True))

        return ft.Container(padding=8, bgcolor="#FAFAFA", border_radius=10, content=ft.Column([header, content_holder], spacing=4))

    def build_book_notes_block(aid, hid, hive):
        notes_list = []
        hive_note = (hive.get("notes") or "").strip()
        if hive_note: notes_list.append(("Улей", hive_note))

        for i, t in enumerate(hive.get("tiers") or []):
            t_note = (t.get("notes") or "").strip()
            if t_note: notes_list.append((f"Ярус {i + 1}", t_note))

        for i, f in enumerate(hive.get("families_data") or []):
            f_note = (f.get("notes") or "").strip()
            if f_note: notes_list.append((f"Семья {i + 1}", f_note))

        if not notes_list:
            return ft.Container(padding=8, bgcolor="#FAFAFA", border_radius=10, content=ft.Text("📝 Примечаний нет", size=12, color="#999999", italic=True))

        content_holder = ft.Container(visible=False)
        arrow_ref = {"icon": ft.Icon(Icons.ARROW_DROP_DOWN, color=HONEY, size=20)}

        def toggle(e):
            content_holder.visible = not content_holder.visible
            arrow_ref["icon"].name = (Icons.ARROW_DROP_UP if content_holder.visible else Icons.ARROW_DROP_DOWN)
            page.update()

        header = ft.Container(
            on_click=toggle, ink=True, padding=6, border_radius=6,
            content=ft.Row([
                ft.Text(f"📝 Примечания ({len(notes_list)})", size=13, weight=ft.FontWeight.BOLD, expand=True),
                ft.Container(content=arrow_ref["icon"]),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER))

        items = []
        for label, text in notes_list:
            items.append(ft.Container(
                padding=8, margin=ft.margin.only(left=16), bgcolor="#FFFFFF", border_radius=6, border=ft.border.all(1, "#E0E0E0"),
                content=ft.Column([
                    ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color="#666666"),
                    ft.Text(text, size=12, color="#333333", italic=True),
                ], spacing=2)))

        content_holder.content = ft.Column(items, spacing=6)
        return ft.Container(padding=8, bgcolor="#FAFAFA", border_radius=10, content=ft.Column([header, content_holder], spacing=4))

    def build_book_hive_card(aid, h, hive_measurements, events, today_str):
        hid = h["id"]
        hive_number = (h.get("number") or "").strip()
        hive_color = h.get("color") or WOOD_LIGHT
        tiers = h.get("tiers") or []
        families = h.get("families_data") or []
        fam_count = len(families)

        preview_hive = {
            "color": hive_color, "number": hive_number, "families": str(fam_count), "photo": "",
            "tiers": [{"color": t.get("color") or hive_color, "height": t.get("height", 150), "photo": ""} for t in tiers],
        }
        preview_visual = build_hive_visual(preview_hive, 80, 50, scale_factor=0.3, is_preview=True)

        content_holder = ft.Container(visible=False)
        arrow_ref = {"icon": ft.Icon(Icons.ARROW_DROP_DOWN, color=HONEY, size=24)}

        def toggle(e):
            content_holder.visible = not content_holder.visible
            arrow_ref["icon"].name = (Icons.ARROW_DROP_UP if content_holder.visible else Icons.ARROW_DROP_DOWN)
            page.update()

        display_number = f"Улей {hive_number}" if hive_number else "Улей"
        tiers_word = plural_ru(len(tiers), "ярус", "яруса", "ярусов")
        if fam_count == 0: fam_summary = "нет семей"
        else:
            fam_word = plural_ru(fam_count, "семья", "семьи", "семей")
            fam_summary = f"{fam_count} {fam_word}"
        summary_text = f"{len(tiers)} {tiers_word} · {fam_summary}"

        header = ft.Container(
            on_click=toggle, ink=True, padding=8, border_radius=8,
            content=ft.Row([
                ft.Container(width=5, height=54, bgcolor=hive_color, border_radius=3),
                ft.Container(content=preview_visual, bgcolor="#FAFAFA", border_radius=8, padding=8),
                ft.Column([
                    ft.Text(display_number, size=16, weight=ft.FontWeight.BOLD, color=HONEY),
                    ft.Text(summary_text, size=12, color="#666666"),
                ], spacing=2, expand=True),
                ft.Container(content=arrow_ref["icon"]),
            ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10))

        main_frames = safe_int(h.get("frames"), 0)
        tier_frames_sum = sum(safe_int(t.get("frames"), 0) for t in tiers)
        total_frames = main_frames + tier_frames_sum

        if total_frames > 0:
            if tiers and tier_frames_sum > 0:
                frames_text = f"🔲 Рамок всего: {total_frames} (корпус {main_frames} + ярусы {tier_frames_sum})"
            else:
                frames_text = f"🔲 Рамок всего: {total_frames}"
        else:
            frames_text = "🔲 Рамок: —"

        info_items = [
            ft.Text(f"📐 Размер: {h.get('size') or '600x500'} мм", size=13),
            ft.Text(frames_text, size=13),
        ]
        if h.get("notes"):
            info_items.append(ft.Text(f"📝 {h.get('notes')}", size=12, color="#666666", italic=True))

        if tiers:
            info_items.append(ft.Container(height=2))
            info_items.append(ft.Text(f"📚 Ярусы ({len(tiers)}):", size=13, weight=ft.FontWeight.BOLD))
            for i, t in enumerate(tiers):
                t_color = t.get("color") or hive_color
                frames = t.get("frames") or "—"
                height = t.get("height", 150)
                notes = (t.get("notes") or "").strip()

                info_items.append(ft.Row([
                    ft.Container(width=14, height=14, bgcolor=t_color, border_radius=3, border=ft.border.all(1, WOOD_DARK)),
                    ft.Text(f"Ярус {i + 1}: {height} мм, рамок {frames}", size=12, color="#444444"),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
                if notes:
                    info_items.append(ft.Text(f"   ↳ {notes}", size=11, color="#777777", italic=True))
        else:
            info_items.append(ft.Text("   Доп. ярусов нет", size=12, color="#999999", italic=True))

        info_block = ft.Container(padding=10, bgcolor="#FAFAFA", border_radius=10, content=ft.Column(info_items, spacing=3))

        fam_block = build_book_families_block(aid, hid, h)
        notes_block = build_book_notes_block(aid, hid, h)

        measurements = hive_measurements.get(hid, [])
        if measurements:
            try:
                chart = make_weight_chart(measurements, hives_map={hid: h}, chart_w=500, chart_h=170)
                chart_block = ft.Container(
                    padding=10, bgcolor="#FAFAFA", border_radius=10,
                    content=ft.Column([
                        ft.Text("📊 Изменение веса", size=13, weight=ft.FontWeight.BOLD),
                        chart,
                    ], spacing=6))
            except Exception as ex:
                chart_block = ft.Container(padding=10, bgcolor="#FAFAFA", border_radius=10, content=ft.Text(f"Ошибка графика: {ex}", size=12, color=DANGER))
        else:
            chart_block = ft.Container(padding=10, bgcolor="#FAFAFA", border_radius=10, content=ft.Text("📊 Нет данных о весе", size=12, color="#999999", italic=True))

        hive_events = [ev for ev in events if event_applies_to_hive(ev, hid)]
        hive_events.sort(key=lambda ev: (ev.get("date", ""), ev.get("time", "")))

        if hive_events:
            event_widgets = []
            for ev in hive_events:
                dt = parse_event_dt(ev)
                is_past = dt and dt < datetime.now()
                is_done = ev.get("notified", False)
                color = ("#4CAF50" if is_done else ("#AAAAAA" if is_past else HONEY))

                date_str = ev.get("date", "")
                time_str = ev.get("time", "")
                date_line = f"🗓 {date_str}"
                if time_str: date_line += f" в {time_str}"
                if is_done: date_line += "  ✓"
                elif is_past: date_line += "  (просрочено)"

                event_widgets.append(ft.Container(
                    padding=6, border_radius=6, bgcolor="#FFFFFF", border=ft.border.all(1, color),
                    content=ft.Column([
                        ft.Text(date_line, size=12, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text(f"• {ev.get('title') or 'Событие'}", size=12, color="#333333"),
                        ft.Text(ev.get("notes"), size=11, color="#666666") if ev.get("notes") else ft.Container(),
                    ], spacing=2)))

            events_block = ft.Container(
                padding=10, bgcolor="#FAFAFA", border_radius=10,
                content=ft.Column([
                    ft.Text(f"🗓 События ({len(hive_events)})", size=13, weight=ft.FontWeight.BOLD),
                    *event_widgets,
                ], spacing=6))
        else:
            events_block = ft.Container(padding=10, bgcolor="#FAFAFA", border_radius=10, content=ft.Text("🗓 Событий не запланировано", size=12, color="#999999", italic=True))

        content_holder.content = ft.Column([info_block, fam_block, notes_block, chart_block, events_block], spacing=10)

        return ft.Container(
            padding=10, border_radius=12, bgcolor="#FFFFFF", border=ft.border.all(1, "#E0E0E0"),
            content=ft.Column([header, content_holder], spacing=6))

    # ================= HIVE ON CANVAS =================
    def build_hive_on_canvas(aid, h, canvas_w, canvas_h, attached_scales=None, hives=None):
        attached_scales = attached_scales or []
        h_left, h_top, w_px, total_h, main_h_px = compute_hive_geometry(h, canvas_w, canvas_h)

        families = h.get("families_data") or []
        show_pins = bool(families) and not h.get("photo")

        pin_size = 12
        pin_spacing = 4
        pin_col_w = pin_size if show_pins else 0
        pin_gap = 6 if show_pins else 0
        container_w = w_px + pin_col_w + pin_gap

        scale_h = 28
        scale_gap = 4
        scales_h = len(attached_scales) * (scale_h + scale_gap)
        total_container_h = total_h + scales_h

        c = ft.Container(
            left=h_left, top=h_top, width=container_w, height=total_container_h,
            on_long_press=lambda e: open_quick_actions(aid, h["id"]))

        def on_drag(e):
            c.left = clamp((c.left or 0) + e.delta_x, 0, max(canvas_w - container_w, 0))
            c.top = clamp((c.top or 0) + e.delta_y, 0, max(canvas_h - total_container_h, 0))
            c.update()

        def on_drag_end(e):
            storage.update_hive_position(
                aid, h["id"],
                (c.left or 0) / canvas_w,
                (c.top or 0) / canvas_h)

        hive_gd = ft.GestureDetector(
            content=build_hive_visual(h, w_px, main_h_px, scale_factor=0.25),
            on_tap=lambda e: show_hive_detail(aid, h["id"]),
            on_pan_update=on_drag,
            on_pan_end=on_drag_end,
            drag_interval=16,
        )

        row_items = [hive_gd]
        if show_pins:
            pins = []
            for i, f in enumerate(families):
                age = queen_age_years(f.get("queen_birth_year"))
                age_txt = f"{age} {plural_ru(age, 'год', 'года', 'лет')}" if age is not None else "?"
                pins.append(ft.Container(
                    width=pin_size, height=pin_size, shape=ft.BoxShape.CIRCLE,
                    bgcolor=queen_pin_color(f.get("queen_birth_year")),
                    border=ft.border.all(1.5, queen_pin_border_color(f.get("queen_birth_year"))),
                    tooltip=f"Семья {i + 1}: {age_txt}"
                ))
            pins_col = ft.Column(pins, spacing=pin_spacing, tight=True)
            row_items.append(pins_col)

        hive_row = ft.Row(
            row_items, spacing=pin_gap,
            vertical_alignment=ft.CrossAxisAlignment.START,
            tight=True)

        col_items = [hive_row]

        for s in attached_scales:
            s_meas = list(s.get("measurements") or [])
            if s_meas:
                s_meas.sort(key=lambda m: m.get("date", ""))
                lw = s_meas[-1].get("weight")
                s_label = f"{float(lw):.1f} кг" if lw is not None else "— кг"
            else:
                s_label = "— кг"
            s_color = s.get("color") or SCALE_DEFAULT_COLOR
            s_visual = build_scale_visual(max(w_px * 1.08, 68), scale_h, s_label, s_color)

            s_c = ft.Container(
                content=s_visual,
                on_click=lambda e, sid=s["id"]: show_scale_stats(aid, sid),
                on_long_press=lambda e, sid=s["id"]: open_scale_quick_actions(aid, sid)
            )
            s_row = ft.Row([s_c], width=w_px, alignment=ft.MainAxisAlignment.CENTER)
            s_wrapper = ft.Container(content=s_row, padding=ft.padding.only(top=scale_gap))
            col_items.append(s_wrapper)

        c.content = ft.Column(col_items, spacing=0, tight=True)
        return c

    # ================= SCALE VISUALS =================
    def build_scale_visual(w, h, label, color):
        return ft.Container(
            width=w, height=h, bgcolor=color,
            border_radius=ft.border_radius.only(top_left=3, top_right=3, bottom_left=8, bottom_right=8),
            border=ft.border.all(2, "#37474F"),
            padding=ft.padding.symmetric(2, 8), alignment=ft.alignment.center,
            shadow=ft.BoxShadow(blur_radius=3, color="#00000044", offset=ft.Offset(0, 2)),
            content=ft.Row([
                ft.Container(width=7, height=7, bgcolor="#FFB300", border_radius=4, border=ft.border.all(1, "#000000")),
                ft.Container(
                    bgcolor="#0A0A0A", border_radius=2, padding=ft.padding.symmetric(1, 4),
                    content=ft.Text(label, size=10, color="#FFB300", weight=ft.FontWeight.BOLD, font_family="monospace")),
            ], spacing=4, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True))

    def build_scale_on_canvas(aid, s, canvas_w, canvas_h, hives):
        scale_w = 76
        scale_h = 28

        nx = float(s.get("x", 0.3))
        ny = float(s.get("y", 0.7))
        left = clamp(nx * canvas_w, 0, max(canvas_w - scale_w, 0))
        top = clamp(ny * canvas_h, 0, max(canvas_h - scale_h, 0))

        measurements = list(s.get("measurements") or [])
        if measurements:
            measurements.sort(key=lambda m: m.get("date", ""))
            lw = measurements[-1].get("weight")
            label = f"{float(lw):.1f} кг" if lw is not None else "— кг"
        else:
            label = "— кг"

        color = s.get("color") or SCALE_DEFAULT_COLOR
        visual = build_scale_visual(scale_w, scale_h, label, color)

        c = ft.Container(
            left=left, top=top, width=scale_w, height=scale_h,
            on_long_press=lambda e: open_scale_quick_actions(aid, s["id"]))

        def on_drag(e):
            c.left = clamp((c.left or 0) + e.delta_x, 0, max(canvas_w - scale_w, 0))
            c.top = clamp((c.top or 0) + e.delta_y, 0, max(canvas_h - scale_h, 0))
            c.update()

        def on_drag_end(e):
            cx = (c.left or 0) + scale_w / 2
            cy = (c.top or 0) + scale_h / 2
            best_hid = None
            best_dist = 90
            for h in hives:
                h_left, h_top, h_w, h_total_h, _ = compute_hive_geometry(h, canvas_w, canvas_h)
                h_cx = h_left + h_w / 2
                h_bottom = h_top + h_total_h
                dist = math.hypot(cx - h_cx, cy - h_bottom)
                if dist < best_dist:
                    best_dist = dist
                    best_hid = h["id"]

            if best_hid:
                storage.update_scale(aid, s["id"], {"attached_hive_id": best_hid})
            else:
                storage.update_scale(aid, s["id"], {
                    "attached_hive_id": None,
                    "x": (c.left or 0) / canvas_w,
                    "y": (c.top or 0) / canvas_h,
                })
            show_apiary(aid)

        gd = ft.GestureDetector(
            content=visual,
            on_tap=lambda e: show_scale_stats(aid, s["id"]),
            on_pan_update=on_drag,
            on_pan_end=on_drag_end,
            drag_interval=16,
        )
        c.content = gd
        return c

    # ================= HIVE VISUAL =================
    def _number_overlay(h, w):
        number_str = (h.get("number") or "").strip()
        if not number_str: return ft.Container()
        return ft.Container(
            right=4, top=4, bgcolor="#000000AA", border_radius=4, padding=ft.padding.symmetric(2, 6),
            content=ft.Text(number_str, color="#FFFFFF", size=max(8, int(w / 12)), weight=ft.FontWeight.BOLD))

    def build_hive_visual(h, w, main_h, scale_factor=1.0, is_preview=False):
        hive_color = h.get("color") or WOOD_LIGHT
        tiers = h.get("tiers") or []
        controls = []

        for tier in reversed(tiers):
            tier_color = tier.get("color") or hive_color
            t_height = tier.get("height", 150) * scale_factor
            photo_rel = tier.get("photo") or ""

            if not is_preview and storage.photo_exists(photo_rel):
                photo_abs = storage.get_photo_abs(photo_rel)
                controls.append(ft.Container(
                    width=w, height=t_height, border_radius=4, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    content=ft.Image(src=photo_abs.as_posix(), fit=ft.ImageFit.COVER, width=w, height=t_height)))
            else:
                controls.append(ft.Container(
                    width=w, height=t_height, bgcolor=tier_color, border_radius=4, border=ft.border.all(1, WOOD_DARK)))

        photo_rel = h.get("photo") or ""
        if not is_preview and storage.photo_exists(photo_rel):
            photo_abs = storage.get_photo_abs(photo_rel)
            controls.append(ft.Container(
                width=w, height=main_h, border_radius=8, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Stack([
                    ft.Image(src=photo_abs.as_posix(), fit=ft.ImageFit.COVER, width=w, height=main_h),
                    _number_overlay(h, w),
                ])))
        else:
            fam_real = safe_int(h.get("families"), 0)
            fam_entrances = max(1, fam_real)
            dot_size = max(3, int(w / 15))
            entrances = ft.Row(
                [ft.Container(width=dot_size, height=dot_size, bgcolor=ENTRANCE, border_radius=dot_size // 2) for _ in range(fam_entrances)],
                alignment=ft.MainAxisAlignment.CENTER, spacing=3)

            f_size = max(8, min(16, int(w / 8)))
            f_size_sub = max(6, f_size - 3)
            txt_color = "#FFFFFF"

            number_str = (h.get("number") or "").strip()
            text_items = []
            if number_str:
                text_items.append(ft.Text(number_str, size=f_size, color=txt_color, weight=ft.FontWeight.BOLD))

            if fam_real > 0:
                fam_word = plural_ru(fam_real, "семья", "семьи", "семей")
                text_items.append(ft.Text(f"{fam_real} {fam_word}", size=f_size_sub, color=txt_color))

            controls.append(ft.Container(
                width=w, height=main_h, bgcolor=hive_color, border_radius=ft.border_radius.only(bottom_left=8, bottom_right=8), padding=4,
                content=ft.Column([
                    *text_items,
                    ft.Container(expand=True),
                    entrances,
                ], spacing=0, alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER)))

        return ft.Column(controls, spacing=TIER_SPACING, tight=True)

    # ================= QUICK ACTIONS =================
    def open_quick_actions(aid, hid):
        hive = storage.get_hive(aid, hid)
        if not hive: return

        def edit_action(e):
            close_dialog(dialog)
            open_hive_dialog(aid, hive, hid, on_close=lambda: show_apiary(aid))

        def tiers_action(e):
            close_dialog(dialog)
            open_visual_tier_editor(aid, hid, on_close=lambda: show_apiary(aid))

        def color_action(e):
            close_dialog(dialog)
            open_color_dialog(aid, hid, on_close=lambda: show_apiary(aid))

        def event_action(e):
            close_dialog(dialog)
            open_event_dialog(aid, preselected_hives=[hid], default_date=cal_state["selected"])

        def delete_action(e):
            close_dialog(dialog)
            confirm_delete_hive(aid, hid)

        number_str = (hive.get("number") or "").strip()
        title_text = f"Улей {number_str}" if number_str else "Улей"

        dialog = ft.AlertDialog(
            title=ft.Text(title_text),
            content=ft.Column([
                ft.ListTile(leading=ft.Icon(Icons.EDIT), title=ft.Text("Редактировать улей"), on_click=edit_action),
                ft.ListTile(leading=ft.Icon(Icons.VIEW_WEEK), title=ft.Text("Управление ярусами"), on_click=tiers_action),
                ft.ListTile(leading=ft.Icon(Icons.PALETTE), title=ft.Text("Покрасить"), on_click=color_action),
                ft.ListTile(leading=ft.Icon(Icons.CALENDAR_MONTH), title=ft.Text("Назначить событие"), on_click=event_action),
                ft.ListTile(leading=ft.Icon(Icons.DELETE, color=DANGER), title=ft.Text("Удалить улей", color=DANGER), on_click=delete_action),
            ], tight=True, spacing=0),
            actions=[ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog))])
        open_dialog(dialog)

    # ================= HIVE DETAIL =================
    def show_hive_detail(aid, hid):
        nonlocal current_aid, current_hid
        current_aid = aid
        current_hid = hid
        hive = storage.get_hive(aid, hid)
        if not hive: return show_apiary(aid)

        page.bgcolor = "#FFFFFF"
        body.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        body.controls.clear()

        number_str = (hive.get("number") or "").strip()
        title_text = f"Улей {number_str}" if number_str else "Улей"

        body.controls.append(ft.Row([
            ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: show_apiary(aid)),
            ft.Text(title_text, size=20, weight=ft.FontWeight.BOLD, expand=True),
            ft.IconButton(Icons.EDIT, icon_color=HONEY, on_click=lambda e: open_hive_dialog(aid, hive, hid)),
            ft.IconButton(Icons.DELETE, icon_color=DANGER, on_click=lambda e: confirm_delete_hive(aid, hid)),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        photo_rel = hive.get("photo") or ""

        if storage.photo_exists(photo_rel):
            photo_abs = storage.get_photo_abs(photo_rel)
            photo_block = ft.Column([
                ft.Image(src=photo_abs.as_posix(), height=220, fit=ft.ImageFit.COVER, border_radius=12),
                ft.Row([
                    ft.TextButton("Заменить фото", icon=Icons.PHOTO_CAMERA, on_click=lambda e: pick_photo(e, aid, hid)),
                    ft.TextButton("Очистить фото", icon=Icons.DELETE, on_click=lambda e: clear_main_photo(aid, hid)),
                ], alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=4)
        else:
            photo_block = ft.Column([
                ft.Container(
                    height=120, bgcolor=SOFT_YELLOW, border_radius=12, alignment=ft.alignment.center,
                    content=ft.Column([
                        ft.Icon(Icons.PHOTO_CAMERA, size=40, color=HONEY),
                        ft.Text("Фото не загружено", color="#666666"),
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)),
                ft.Button("Загрузить фото", icon=Icons.PHOTO_CAMERA, style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=lambda e: pick_photo(e, aid, hid)),
            ], spacing=8)

        info = ft.Column(spacing=4, controls=[
            info_row("Размер (мм)", hive.get("size") or "600x500",
                     on_long_press=lambda e: open_edit_param_dialog(aid, hid, "size", "Размер (мм, напр. 600x500)", hive.get("size"))),
            info_row("Количество рамок", hive.get("frames") or "—",
                     on_long_press=lambda e: open_edit_param_dialog(aid, hid, "frames", "Количество рамок", hive.get("frames"), is_number=True)),
            info_row("Цвет", hive.get("color") or WOOD_LIGHT),
            info_row("Заметки", hive.get("notes") or "—",
                     on_long_press=lambda e: open_edit_param_dialog(aid, hid, "notes", "Заметки", hive.get("notes"), is_multiline=True)),
        ])

        info_hint = ft.Text("Нажмите и удерживайте параметр, чтобы изменить его", size=12, color="#999999", italic=True, text_align=ft.TextAlign.CENTER)

        families_section = build_families_section(aid, hid, hive)
        tiers_block = build_tiers_section(aid, hid, hive)

        all_events = storage.list_events(aid)
        today_str = datetime.now().strftime("%Y-%m-%d")
        hive_events = [ev for ev in all_events if event_applies_to_hive(ev, hid) and ev.get("date", "") >= today_str]
        hive_events.sort(key=lambda ev: (ev.get("date", ""), ev.get("time", "")))

        events_section = ft.Container(
            bgcolor=SOFT_YELLOW, border_radius=12, padding=12,
            content=ft.Column([
                ft.Row([
                    ft.Text("Предстоящие события", size=16, weight=ft.FontWeight.BOLD, expand=True),
                    ft.TextButton("Добавить", icon=Icons.ADD, on_click=lambda e: open_event_dialog(aid, preselected_hives=[hid], default_date=cal_state["selected"])),
                ]),
                *([event_card(aid, ev, hive_context=True) for ev in hive_events[:5]] or [ft.Text("Нет предстоящих событий", color="#666666", size=13)]),
            ], spacing=8))

        body.controls.append(ft.Column([
            photo_block,
            ft.Container(bgcolor=SOFT_YELLOW, border_radius=12, padding=16, content=info),
            info_hint,
            families_section,
            tiers_block,
            events_section,
        ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True))
        page.update()

    def info_row(label, value, on_long_press=None):
        content = ft.Row([
            ft.Text(label, weight=ft.FontWeight.BOLD, expand=2, size=14),
            ft.Text(str(value), expand=3, size=14),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        if on_long_press:
            return ft.Container(content=content, on_long_press=on_long_press, padding=8, border_radius=8, ink=True)
        return ft.Container(content=content, padding=8)

    def open_edit_param_dialog(aid, hid, field, label, current_value, is_number=False, is_multiline=False):
        val_str = str(current_value) if current_value is not None else ""
        tf = ft.TextField(
            label=label, value=val_str, autofocus=True, multiline=is_multiline,
            min_lines=3 if is_multiline else 1,
            keyboard_type=(ft.KeyboardType.NUMBER if is_number else ft.KeyboardType.TEXT))

        def save_param(e):
            new_val = tf.value.strip()
            payload = {field: new_val}
            if field == "families": payload[field] = str(max(1, safe_int(new_val, 1)))

            def do_save():
                storage.update_hive(aid, hid, payload)
                close_dialog(dialog)
                show_hive_detail(aid, hid)

            confirm_action("Сохранение", "Применить изменения параметра?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text(f"Изменить: {label}"),
            content=ft.Column([tf], tight=True),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save_param),
            ])
        open_dialog(dialog)

    # ================= FAMILIES SECTION =================
    def build_families_section(aid, hid, hive):
        families = hive.get("families_data") or []
        fam_word = plural_ru(len(families), "семья", "семьи", "семей")
        controls = [
            ft.Row([
                ft.Text(f"🐝 Семьи ({len(families)}) · {len(families)} {fam_word}", size=16, weight=ft.FontWeight.BOLD, expand=True),
                ft.TextButton("+ Добавить", icon=Icons.ADD, on_click=lambda e: open_family_dialog(aid, hid)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]

        if not families:
            controls.append(ft.Container(
                padding=12, bgcolor="#F5F5F5", border_radius=8,
                content=ft.Text("В улье пока нет семей. Нажмите «+ Добавить», чтобы добавить первую.", size=12, color="#666666", italic=True)))
        else:
            for i, f in enumerate(families):
                age = queen_age_years(f.get("queen_birth_year"))
                age_text = f"{age} {plural_ru(age, 'год', 'года', 'лет')}" if age is not None else "—"
                pin_color = queen_pin_color(f.get("queen_birth_year"))
                pin_border = queen_pin_border_color(f.get("queen_birth_year"))

                controls.append(ft.Container(
                    padding=10, bgcolor="#F5F5F5", border_radius=8,
                    content=ft.Column([
                        ft.Row([
                            ft.Container(width=14, height=14, shape=ft.BoxShape.CIRCLE, bgcolor=pin_color, border=ft.border.all(1.5, pin_border)),
                            ft.Text(f"Семья {i + 1} · матка {age_text}", size=13, weight=ft.FontWeight.BOLD, expand=True),
                            ft.IconButton(Icons.EDIT, icon_size=18, icon_color=HONEY, tooltip="Редактировать", on_click=lambda e, ff=f: open_family_dialog(aid, hid, ff)),
                            ft.IconButton(Icons.DELETE, icon_size=18, icon_color=DANGER, tooltip="Удалить", on_click=lambda e, fid=f["id"]: confirm_delete_family(aid, hid, fid)),
                        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text(f"Состояние: {f.get('state') or '—'}", size=12, color="#555555") if f.get("state") else ft.Container(),
                        ft.Text(f.get("notes") or "", size=12, color="#666666") if f.get("notes") else ft.Container(),
                    ], spacing=3)))

        return ft.Container(bgcolor=SOFT_YELLOW, border_radius=12, padding=12, content=ft.Column(controls, spacing=8))

    def open_family_dialog(aid, hid, family=None):
        is_edit = family is not None
        current_year = datetime.now().year

        initial_age = ""
        if is_edit:
            age = queen_age_years(family.get("queen_birth_year"))
            if age is not None: initial_age = str(age)

        age_field = ft.TextField(label="Возраст матки (лет)", value=initial_age, keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
        state_field = ft.TextField(label="Состояние семьи", value=(family.get("state") if is_edit else ""))
        notes_field = ft.TextField(label="Описание", value=(family.get("notes") if is_edit else ""), multiline=True, min_lines=3)

        def save(e):
            age_str = age_field.value.strip()
            if not age_str:
                age_field.error_text = "Укажите возраст матки"
                page.update()
                return
            try:
                age = int(age_str)
                if age < 0 or age > 10: raise ValueError
            except Exception:
                age_field.error_text = "Возраст от 0 до 10 лет"
                page.update()
                return

            birth_year = current_year - age
            payload = {"queen_birth_year": birth_year, "queen_age_at_add": age, "state": state_field.value.strip(), "notes": notes_field.value.strip()}

            def do_save():
                if is_edit: storage.update_family(aid, hid, family["id"], payload)
                else: storage.add_family(aid, hid, payload)
                close_dialog(dialog)
                show_hive_detail(aid, hid)

            confirm_action("Сохранение семьи", "Применить изменения?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text("Редактировать семью" if is_edit else "Новая семья"),
            content=ft.Column([age_field, state_field, notes_field], tight=True, spacing=8),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    def confirm_delete_family(aid, hid, fid):
        def do_delete(e):
            storage.delete_family(aid, hid, fid)
            close_dialog(dialog)
            show_hive_detail(aid, hid)

        dialog = ft.AlertDialog(
            title=ft.Text("Удалить семью?"),
            content=ft.Text("Данные о матке и семье будут удалены."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_delete),
            ])
        open_dialog(dialog)

    # ================= TIERS SECTION =================
    def build_tiers_section(aid, hid, hive):
        tiers = hive.get("tiers") or []
        tiers_word = plural_ru(len(tiers), "ярус", "яруса", "ярусов")
        controls = [
            ft.Row([
                ft.Text(f"Ярусы улья ({len(tiers)} {tiers_word})", size=16, weight=ft.FontWeight.BOLD, expand=True),
                ft.TextButton("Визуально", icon=Icons.VIEW_WEEK, tooltip="Визуальный редактор ярусов", on_click=lambda e: open_visual_tier_editor(aid, hid)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]

        controls.append(ft.Container(
            padding=8, bgcolor="#FFF3CD", border_radius=8,
            content=ft.Column([
                ft.Text("Главный ярус (с входами)", size=13, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.TextButton("Заменить фото", icon=Icons.PHOTO_CAMERA, on_click=lambda e: pick_photo(e, aid, hid)),
                    ft.TextButton("Очистить", icon=Icons.DELETE, on_click=lambda e: clear_main_photo(aid, hid)) if hive.get("photo") else ft.Container(),
                ], spacing=4),
            ], spacing=4)))

        for i, tier in enumerate(tiers):
            tier_box = ft.Container(
                padding=8, bgcolor="#F0F0F0", border_radius=8, on_long_press=lambda e, t=tier: open_tier_quick_actions(aid, hid, t),
                content=ft.Column([
                    ft.Row([
                        ft.Text(f"Дополнительный ярус {i + 1}", size=13, weight=ft.FontWeight.BOLD, expand=True),
                        ft.IconButton(Icons.TUNE, icon_size=18, tooltip="Настроить ярус", on_click=lambda e, t=tier: open_tier_settings(aid, hid, t)),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(f"Рамок: {tier.get('frames') or '—'}", size=12, color="#555555"),
                    ft.Text(f"Примечание: {tier.get('notes') or '—'}", size=12, color="#555555"),
                    ft.Row([
                        ft.TextButton("Фото", icon=Icons.PHOTO_CAMERA, on_click=lambda e, tid=tier["id"]: pick_tier_photo(e, aid, hid, tid)),
                        ft.TextButton("Очистить", icon=Icons.DELETE, on_click=lambda e, tid=tier["id"]: clear_tier_photo(aid, hid, tid)) if tier.get("photo") else ft.Container(),
                    ], spacing=4),
                ], spacing=4))
            controls.append(tier_box)

        controls.append(ft.Row([
            ft.Button("Ярус", icon=Icons.ADD, on_click=lambda e: add_tier_clicked(aid, hid)),
            ft.Button("Покрасить", icon=Icons.PALETTE, on_click=lambda e: open_color_dialog(aid, hid)),
        ], spacing=8))

        return ft.Container(bgcolor=SOFT_YELLOW, border_radius=12, padding=12, content=ft.Column(controls, spacing=8))

    def open_tier_quick_actions(aid, hid, tier):
        def settings_action(e):
            close_dialog(dialog)
            open_tier_settings(aid, hid, tier)

        def photo_action(e):
            close_dialog(dialog)
            pick_tier_photo(e, aid, hid, tier["id"])

        def delete_action(e):
            close_dialog(dialog)
            confirm_delete_tier(aid, hid, tier["id"])

        dialog = ft.AlertDialog(
            title=ft.Text("Действия с ярусом"),
            content=ft.Column([
                ft.ListTile(leading=ft.Icon(Icons.TUNE), title=ft.Text("Настроить ярус"), on_click=settings_action),
                ft.ListTile(leading=ft.Icon(Icons.PHOTO_CAMERA), title=ft.Text("Загрузить/Заменить фото"), on_click=photo_action),
                ft.ListTile(leading=ft.Icon(Icons.DELETE, color=DANGER), title=ft.Text("Удалить ярус", color=DANGER), on_click=delete_action),
            ], tight=True, spacing=0),
            actions=[ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog))])
        open_dialog(dialog)

    def add_tier_clicked(aid, hid):
        def do_add():
            storage.add_tier(aid, hid)
            show_hive_detail(aid, hid)
        confirm_action("Добавление яруса", "Добавить новый ярус к этому улью?", do_add)

    def confirm_delete_tier(aid, hid, tid):
        def do_del(e):
            storage.delete_tier(aid, hid, tid)
            close_dialog(dialog)
            show_hive_detail(aid, hid)

        dialog = ft.AlertDialog(
            title=ft.Text("Удалить ярус?"),
            content=ft.Text("Это действие нельзя отменить."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_del),
            ])
        open_dialog(dialog)

    # ================= TIER SETTINGS =================
    def open_tier_settings(aid, hid, tier, on_close=None):
        hive = storage.get_hive(aid, hid)
        if not hive: return

        def close_and_return():
            close_dialog(dialog)
            if on_close: on_close()
            else: show_hive_detail(aid, hid)

        current_color = tier.get("color") or hive.get("color") or WOOD_LIGHT
        r0, g0, b0 = hex_to_rgb(current_color)

        height_field = ft.TextField(label="Высота (мм)", value=str(tier.get("height", 150)), keyboard_type=ft.KeyboardType.NUMBER, width=150)
        frames_field = ft.TextField(label="Кол-во рамок", value=str(tier.get("frames", "")), keyboard_type=ft.KeyboardType.NUMBER)
        notes_field = ft.TextField(label="Примечания", value=str(tier.get("notes", "")), multiline=True, min_lines=2)

        preview_box = ft.Container(alignment=ft.alignment.center, height=100)
        hex_text = ft.Text(current_color, size=12, color="#666666")

        def update_preview(e=None):
            c = rgb_to_hex(int(r.value), int(g.value), int(b.value))
            hex_text.value = c
            temp_hive = {
                "color": "#CCCCCC", "number": "", "families": "1", "photo": "",
                "tiers": [{"color": c, "height": safe_int(height_field.value, 150), "photo": ""}],
            }
            preview_box.content = build_hive_visual(temp_hive, 120, 60, scale_factor=0.25, is_preview=True)
            page.update()

        r = ft.Slider(min=0, max=255, divisions=255, value=r0, label="R {value}", on_change=update_preview, active_color="#D32F2F", width=340)
        g = ft.Slider(min=0, max=255, divisions=255, value=g0, label="G {value}", on_change=update_preview, active_color="#388E3C", width=340)
        b = ft.Slider(min=0, max=255, divisions=255, value=b0, label="B {value}", on_change=update_preview, active_color="#1976D2", width=340)
        height_field.on_change = update_preview

        def apply(e):
            color = rgb_to_hex(int(r.value), int(g.value), int(b.value))
            h_val = max(10, safe_int(height_field.value, 150))

            def do_apply():
                storage.update_tier(aid, hid, tier["id"], {
                    "color": color, "height": h_val,
                    "frames": frames_field.value.strip(),
                    "notes": notes_field.value.strip(),
                })
                close_and_return()

            confirm_action("Настройки яруса", "Применить изменения яруса?", do_apply)

        update_preview()

        dialog = ft.AlertDialog(
            title=ft.Text("Настройки яруса"),
            content=ft.Container(
                width=380, height=500,
                content=ft.Column([
                    preview_box,
                    ft.Row([height_field, hex_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    frames_field,
                    notes_field,
                    ft.Text("Цвет:"),
                    ft.Text("Красный (R)"), r,
                    ft.Text("Зелёный (G)"), g,
                    ft.Text("Синий (B)"), b,
                ], spacing=8, scroll=ft.ScrollMode.AUTO)),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_and_return()),
                ft.Button("Применить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=apply),
            ])
        open_dialog(dialog)

    def open_color_dialog(aid, hid, on_close=None):
        hive = storage.get_hive(aid, hid)
        if not hive: return
        current = hive.get("color") or WOOD_LIGHT
        r0, g0, b0 = hex_to_rgb(current)

        def close_and_return():
            close_dialog(dialog)
            if on_close: on_close()
            elif current_hid == hid: show_hive_detail(aid, hid)
            else: show_apiary(aid)

        preview_box = ft.Container(alignment=ft.alignment.center, height=180)
        hex_text = ft.Text(current, size=12, color="#666666")
        whole = ft.Checkbox(label="Покрасить весь улей (включая ярусы)", value=True)

        def update_preview(e=None):
            c = rgb_to_hex(int(r.value), int(g.value), int(b.value))
            hex_text.value = c
            tiers_src = hive.get("tiers") or []
            temp_hive = {
                "color": c, "number": hive.get("number", ""), "families": hive.get("families", "1"), "photo": "",
                "tiers": [{"color": c if whole.value else (t.get("color") or c), "height": t.get("height", 150), "photo": ""} for t in tiers_src],
            }
            preview_box.content = build_hive_visual(temp_hive, 120, 60, scale_factor=0.25, is_preview=True)
            page.update()

        r = ft.Slider(min=0, max=255, divisions=255, value=r0, label="R {value}", on_change=update_preview, active_color="#D32F2F", width=340)
        g = ft.Slider(min=0, max=255, divisions=255, value=g0, label="G {value}", on_change=update_preview, active_color="#388E3C", width=340)
        b = ft.Slider(min=0, max=255, divisions=255, value=b0, label="B {value}", on_change=update_preview, active_color="#1976D2", width=340)
        whole.on_change = update_preview

        def apply(e):
            color = rgb_to_hex(int(r.value), int(g.value), int(b.value))

            def do_apply():
                storage.set_hive_color(aid, hid, color, whole.value)
                close_and_return()

            confirm_action("Покраска", "Применить этот цвет к улью?", do_apply)

        update_preview()

        dialog = ft.AlertDialog(
            title=ft.Text("Покрасить улей"),
            content=ft.Container(
                width=380, height=520,
                content=ft.Column([
                    preview_box,
                    ft.Row([hex_text], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Text("Красный (R)"), r,
                    ft.Text("Зелёный (G)"), g,
                    ft.Text("Синий (B)"), b,
                    whole,
                ], spacing=8, scroll=ft.ScrollMode.AUTO)),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_and_return()),
                ft.Button("Применить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=apply),
            ])
        open_dialog(dialog)

    # ================= VISUAL TIER EDITOR =================
    def open_visual_tier_editor(aid, hid, on_close=None):
        hive = storage.get_hive(aid, hid)
        if not hive: return

        content_holder = ft.Container()

        def rebuild_visual():
            hv = storage.get_hive(aid, hid) or {}
            hive_color = hv.get("color") or WOOD_LIGHT
            tiers = hv.get("tiers") or []

            visual_items = []
            for idx, tier in enumerate(reversed(tiers)):
                real_num = len(tiers) - idx
                t_color = tier.get("color") or hive_color
                t_h = max(35, min(75, int((tier.get("height", 150) or 150) * 0.3)))
                txt_color = "#FFFFFF"
                frames_txt = tier.get("frames") or "—"

                visual_items.append(ft.Container(
                    width=200, height=t_h, bgcolor=t_color, border_radius=6, border=ft.border.all(1, WOOD_DARK),
                    alignment=ft.alignment.center, ink=True, on_click=lambda e, t=tier: show_tier_form(t),
                    content=ft.Column([
                        ft.Text(f"Ярус {real_num}", size=11, color=txt_color, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Рамок: {frames_txt}", size=9, color=txt_color),
                    ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                ))

            main_txt_color = "#FFFFFF"
            number_str = (hv.get("number") or "").strip()
            main_label = number_str if number_str else "Улей"
            fam_count = len(hv.get("families_data") or [])
            fam_word = plural_ru(fam_count, "семья", "семьи", "семей")
            fam_line = f"{fam_count} {fam_word}" if fam_count else ""

            main_col = [ft.Text(main_label, size=14, color=main_txt_color, weight=ft.FontWeight.BOLD)]
            if fam_line: main_col.append(ft.Text(fam_line, size=10, color=main_txt_color))

            visual_items.append(ft.Container(
                width=200, height=80, bgcolor=hive_color,
                border_radius=ft.border_radius.only(bottom_left=10, bottom_right=10),
                border=ft.border.all(1, WOOD_DARK), alignment=ft.alignment.center, ink=True,
                on_click=lambda e: show_main_form(),
                content=ft.Column(main_col, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ))

            content_holder.content = ft.Column([
                ft.Text("Нажмите на элемент, чтобы отредактировать", size=11, color="#666666", italic=True),
                ft.Container(
                    content=ft.Column(visual_items, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=16, bgcolor="#F5F5F5", border_radius=12,
                    alignment=ft.alignment.center,
                    border=ft.border.all(1, "#E0E0E0"),
                ),
                ft.Row([
                    ft.Button("+ Ярус", icon=Icons.ADD,
                              on_click=lambda e: do_add_tier(),
                              style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF")),
                    ft.OutlinedButton("Покрасить", icon=Icons.PALETTE,
                                      on_click=lambda e: do_paint()),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
            ], tight=True, spacing=12, width=300, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            page.update()

        def show_tier_form(tier):
            current_color = tier.get("color") or hive.get("color") or WOOD_LIGHT
            r0, g0, b0 = hex_to_rgb(current_color)

            height_field = ft.TextField(label="Высота (мм)", value=str(tier.get("height", 150)), keyboard_type=ft.KeyboardType.NUMBER, width=150)
            frames_field = ft.TextField(label="Кол-во рамок", value=str(tier.get("frames", "")), keyboard_type=ft.KeyboardType.NUMBER)
            notes_field = ft.TextField(label="Примечания", value=str(tier.get("notes", "")), multiline=True, min_lines=2)

            preview_box = ft.Container(alignment=ft.alignment.center, height=100)
            hex_text = ft.Text(current_color, size=12, color="#666666")

            def update_preview(e=None):
                c = rgb_to_hex(int(r.value), int(g.value), int(b.value))
                hex_text.value = c
                temp_hive = {
                    "color": "#CCCCCC", "number": "", "families": "1", "photo": "",
                    "tiers": [{"color": c, "height": safe_int(height_field.value, 150), "photo": ""}],
                }
                preview_box.content = build_hive_visual(temp_hive, 120, 60, scale_factor=0.25, is_preview=True)
                page.update()

            r = ft.Slider(min=0, max=255, divisions=255, value=r0, label="R {value}", on_change=update_preview, active_color="#D32F2F", width=340)
            g = ft.Slider(min=0, max=255, divisions=255, value=g0, label="G {value}", on_change=update_preview, active_color="#388E3C", width=340)
            b = ft.Slider(min=0, max=255, divisions=255, value=b0, label="B {value}", on_change=update_preview, active_color="#1976D2", width=340)
            height_field.on_change = update_preview

            def do_apply(e):
                color = rgb_to_hex(int(r.value), int(g.value), int(b.value))
                h_val = max(10, safe_int(height_field.value, 150))
                storage.update_tier(aid, hid, tier["id"], {
                    "color": color, "height": h_val,
                    "frames": frames_field.value.strip(),
                    "notes": notes_field.value.strip(),
                })
                rebuild_visual()

            update_preview()

            content_holder.content = ft.Column([
                ft.Row([
                    ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: rebuild_visual(), tooltip="Назад к списку"),
                    ft.Text("Настройки яруса", size=15, weight=ft.FontWeight.BOLD, expand=True),
                ]),
                preview_box,
                ft.Row([height_field, hex_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                frames_field,
                notes_field,
                ft.Text("Цвет:"),
                ft.Text("Красный (R)"), r,
                ft.Text("Зелёный (G)"), g,
                ft.Text("Синий (B)"), b,
                ft.Row([
                    ft.TextButton("Отмена", on_click=lambda e: rebuild_visual()),
                    ft.Button("Применить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=do_apply),
                ], alignment=ft.MainAxisAlignment.END, spacing=8),
            ], tight=True, scroll=ft.ScrollMode.AUTO, spacing=6, width=360)
            page.update()

        def show_main_form():
            hv = storage.get_hive(aid, hid) or {}
            number = ft.TextField(label="Номер улья", value=hv.get("number", ""))
            size = ft.TextField(label="Размер (ШxВ мм)", value=hv.get("size", ""))
            frames = ft.TextField(label="Количество рамок", keyboard_type=ft.KeyboardType.NUMBER, value=hv.get("frames", ""))
            notes = ft.TextField(label="Заметки", multiline=True, min_lines=2, value=hv.get("notes", ""))

            def do_save(e):
                payload = {
                    "number": number.value.strip(),
                    "size": size.value.strip(),
                    "frames": frames.value.strip(),
                    "notes": notes.value.strip(),
                }
                storage.update_hive(aid, hid, payload)
                rebuild_visual()

            content_holder.content = ft.Column([
                ft.Row([
                    ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: rebuild_visual(), tooltip="Назад к списку"),
                    ft.Text("Параметры главного корпуса", size=15, weight=ft.FontWeight.BOLD, expand=True),
                ]),
                number, size, frames, notes,
                ft.Row([
                    ft.TextButton("Отмена", on_click=lambda e: rebuild_visual()),
                    ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=do_save),
                ], alignment=ft.MainAxisAlignment.END, spacing=8),
            ], tight=True, scroll=ft.ScrollMode.AUTO, spacing=8, width=360)
            page.update()

        def do_add_tier():
            storage.add_tier(aid, hid)
            rebuild_visual()

        def do_paint():
            hv = storage.get_hive(aid, hid) or {}
            current = hv.get("color") or WOOD_LIGHT
            r0, g0, b0 = hex_to_rgb(current)

            preview_box = ft.Container(alignment=ft.alignment.center, height=180)
            hex_text = ft.Text(current, size=12, color="#666666")
            whole = ft.Checkbox(label="Покрасить весь улей (включая ярусы)", value=True)

            def update_preview(e=None):
                c = rgb_to_hex(int(r.value), int(g.value), int(b.value))
                hex_text.value = c
                tiers_src = hv.get("tiers") or []
                temp_hive = {
                    "color": c, "number": hv.get("number", ""), "families": hv.get("families", "1"), "photo": "",
                    "tiers": [{"color": c if whole.value else (t.get("color") or c), "height": t.get("height", 150), "photo": ""} for t in tiers_src],
                }
                preview_box.content = build_hive_visual(temp_hive, 120, 60, scale_factor=0.25, is_preview=True)
                page.update()

            r = ft.Slider(min=0, max=255, divisions=255, value=r0, label="R {value}", on_change=update_preview, active_color="#D32F2F", width=340)
            g = ft.Slider(min=0, max=255, divisions=255, value=g0, label="G {value}", on_change=update_preview, active_color="#388E3C", width=340)
            b = ft.Slider(min=0, max=255, divisions=255, value=b0, label="B {value}", on_change=update_preview, active_color="#1976D2", width=340)
            whole.on_change = update_preview

            def do_apply(e):
                c = rgb_to_hex(int(r.value), int(g.value), int(b.value))
                storage.set_hive_color(aid, hid, c, whole.value)
                rebuild_visual()

            update_preview()

            content_holder.content = ft.Column([
                ft.Row([
                    ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: rebuild_visual(), tooltip="Назад к списку"),
                    ft.Text("Покрасить улей", size=15, weight=ft.FontWeight.BOLD, expand=True),
                ]),
                preview_box,
                ft.Row([hex_text], alignment=ft.MainAxisAlignment.CENTER),
                ft.Text("Красный (R)"), r,
                ft.Text("Зелёный (G)"), g,
                ft.Text("Синий (B)"), b,
                whole,
                ft.Row([
                    ft.TextButton("Отмена", on_click=lambda e: rebuild_visual()),
                    ft.Button("Применить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=do_apply),
                ], alignment=ft.MainAxisAlignment.END, spacing=8),
            ], tight=True, scroll=ft.ScrollMode.AUTO, spacing=6, width=360)
            page.update()

        rebuild_visual()

        dialog = ft.AlertDialog(
            title=ft.Text("Управление ярусами"),
            content=ft.Container(
                width=360, height=560,
                content=ft.Column([content_holder], scroll=ft.ScrollMode.AUTO)),
            actions=[ft.TextButton(
                "Закрыть",
                on_click=lambda e: (
                    close_dialog(dialog),
                    on_close() if on_close else (
                        show_hive_detail(aid, hid) if current_hid == hid else show_apiary(aid)
                    )
                ))],
        )
        open_dialog(dialog)

    # ================= SCALE STATS =================
    def _stat_tile(title, value, color):
        return ft.Container(
            padding=10, border_radius=10, bgcolor="#FFFFFF", border=ft.border.all(1, color + "55"),
            content=ft.Column([
                ft.Text(title, size=11, color="#666666"),
                ft.Text(value, size=15, weight=ft.FontWeight.BOLD, color=color),
            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=110)

    def show_scale_stats(aid, sid):
        scale = storage.get_scale(aid, sid)
        if not scale: return

        holder = ft.Container()

        def refresh():
            sc = storage.get_scale(aid, sid) or {}
            hives_list = storage.list_hives(aid)
            hives_map = {h["id"]: h for h in hives_list}
            measurements = list(sc.get("measurements") or [])
            measurements.sort(key=lambda m: m.get("date", ""), reverse=True)

            if not measurements:
                table = ft.Container(
                    padding=20, alignment=ft.alignment.center,
                    content=ft.Column([
                        ft.Icon(Icons.TABLE_ROWS, size=40, color="#CCCCCC"),
                        ft.Text("Пока нет измерений", color="#666666"),
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
            else:
                rows = []
                prev_weight_by_hive = {}
                for m in measurements:
                    w = float(m.get("weight", 0))
                    m_hid = m.get("hive_id")

                    delta_str = ""
                    prev_w = prev_weight_by_hive.get(m_hid)
                    if prev_w is not None:
                        diff = w - prev_w
                        sign = "+" if diff >= 0 else ""
                        delta_str = f"{sign}{diff:.2f}"
                    delta_color = (DANGER if delta_str.startswith("-") else "#388E3C")

                    m_hive = hives_map.get(m_hid) if m_hid else None
                    if m_hive:
                        m_hive_num = (m_hive.get("number") or "").strip()
                        hive_label = f"№{m_hive_num}" if m_hive_num else "Улей"
                    else:
                        hive_label = "—"

                    rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(m.get("date", ""), size=12)),
                        ft.DataCell(ft.Text(hive_label, size=12, color="#555555")),
                        ft.DataCell(ft.Text(f"{w:.2f} кг", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(delta_str, size=11, color=delta_color if delta_str else "#999999")),
                        ft.DataCell(ft.Row([
                            ft.IconButton(
                                Icons.EDIT, icon_size=16, icon_color=HONEY, tooltip="Изменить",
                                on_click=lambda e, mid=m["id"], dt=m.get("date", ""), wt=m.get("weight", 0), hv=m.get("hive_id"):
                                    open_measurement_dialog(aid, sid, mid, dt, wt, refresh, current_hive_id=hv)),
                            ft.IconButton(
                                Icons.DELETE, icon_size=16, icon_color=DANGER, tooltip="Удалить",
                                on_click=lambda e, mid=m["id"]: confirm_delete_measurement(aid, sid, mid, refresh)),
                        ], spacing=0)),
                    ]))
                    prev_weight_by_hive[m_hid] = w

                table = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Дата", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Улей", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Вес", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Δ", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("", size=12)),
                    ],
                    rows=rows, column_spacing=18, heading_row_height=30, data_row_min_height=36, data_row_max_height=44)

            chart = ft.Container(
                content=make_weight_chart(measurements, hives_map=hives_map, chart_w=540, chart_h=240),
                padding=8, bgcolor="#FAFAFA", border_radius=10)

            def add_measurement(e):
                open_measurement_dialog(aid, sid, None, None, None, refresh)

            def rename_scale(e):
                tf = ft.TextField(label="Название весов", value=sc.get("name", "Весы"), autofocus=True)

                def do_rename(ev):
                    new_name = tf.value.strip() or "Весы"
                    storage.update_scale(aid, sid, {"name": new_name})
                    close_dialog(rdialog)
                    refresh()
                    page.update()

                rdialog = ft.AlertDialog(
                    title=ft.Text("Переименовать весы"),
                    content=ft.Column([tf], tight=True),
                    actions=[
                        ft.TextButton("Отмена", on_click=lambda ev: close_dialog(rdialog)),
                        ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=do_rename),
                    ])
                open_dialog(rdialog)

            scale_color = sc.get("color") or SCALE_DEFAULT_COLOR
            header = ft.Row([
                ft.Container(alignment=ft.alignment.center, content=build_scale_visual(70, 24, "0.0 кг", scale_color)),
                ft.Text(sc.get("name", "Весы"), size=18, weight=ft.FontWeight.BOLD, expand=True),
                ft.IconButton(Icons.EDIT, icon_color=HONEY, tooltip="Переименовать", on_click=rename_scale),
                ft.Button("+ Замер", icon=Icons.ADD, style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=add_measurement),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

            stats_row = ft.Container()
            if measurements:
                weights_only = [float(m.get("weight", 0)) for m in measurements]
                cur = weights_only[0]
                mx = max(weights_only)
                mn = min(weights_only)
                avg = sum(weights_only) / len(weights_only)
                stats_row = ft.Row([
                    _stat_tile("Сейчас", f"{cur:.1f} кг", HONEY),
                    _stat_tile("Макс", f"{mx:.1f} кг", "#388E3C"),
                    _stat_tile("Мин", f"{mn:.1f} кг", DANGER),
                    _stat_tile("Сред.", f"{avg:.1f} кг", "#1976D2"),
                ], spacing=8, wrap=True)

            holder.content = ft.Column([
                header,
                stats_row,
                ft.Container(content=table, padding=4),
                ft.Text("График по датам (кг)", size=13, weight=ft.FontWeight.BOLD, color="#666666"),
                chart,
            ], spacing=12, scroll=ft.ScrollMode.AUTO)
            page.update()

        refresh()

        dialog = ft.AlertDialog(
            title=ft.Text(f"📊 {scale.get('name', 'Весы')}"),
            content=ft.Container(width=600, height=600, content=holder),
            actions=[ft.TextButton("Закрыть", on_click=lambda e: close_dialog(dialog))],
        )
        open_dialog(dialog)

    def open_measurement_dialog(aid, sid, mid, date_val, weight_val, on_save, current_hive_id=None):
        is_edit = mid is not None
        hives = storage.list_hives(aid)
        scale = storage.get_scale(aid, sid) or {}
        attached_hive_id = scale.get("attached_hive_id")
        valid_hive_ids = {h["id"] for h in hives}

        if is_edit:
            initial_hive = current_hive_id
        else:
            initial_hive = attached_hive_id
        if initial_hive and initial_hive not in valid_hive_ids:
            initial_hive = None

        hive_options = [ft.dropdown.Option(key="", text="— Без улья —")]
        for h in hives:
            number_str = (h.get("number") or "").strip()
            label = f"№{number_str}" if number_str else "Улей без номера"
            hive_options.append(ft.dropdown.Option(key=h["id"], text=label))

        hive_dropdown = ft.Dropdown(label="Улей", options=hive_options, value=initial_hive or "", width=250)

        attached_note = ft.Container()
        if (not is_edit and attached_hive_id and attached_hive_id in valid_hive_ids):
            attached_note = ft.Text("Улей подставлен автоматически (весы прикреплены). Можно изменить.", size=11, color="#666666", italic=True)

        date_field = ft.TextField(label="Дата (ГГГГ-ММ-ДД)", value=date_val or datetime.now().strftime("%Y-%m-%d"), width=200)
        pick_date_btn = ft.IconButton(
            Icons.CALENDAR_MONTH, tooltip="Выбрать дату",
            on_click=lambda e: open_date_picker(lambda v: (setattr(date_field, "value", v), page.update())))
        date_row = ft.Row([date_field, pick_date_btn])

        weight_field = ft.TextField(label="Вес (кг)", autofocus=True, keyboard_type=ft.KeyboardType.NUMBER, value=(f"{weight_val:.2f}" if weight_val is not None else ""))

        def save(e):
            if not date_field.value.strip():
                date_field.error_text = "Укажите дату"
                page.update()
                return
            try:
                w = float(weight_field.value.strip().replace(",", "."))
                if w <= 0: raise ValueError
            except Exception:
                weight_field.error_text = "Некорректный вес"
                page.update()
                return

            selected_hive = hive_dropdown.value or None

            if is_edit:
                storage.update_measurement(aid, sid, mid, date_field.value.strip(), w, selected_hive)
            else:
                storage.add_measurement(aid, sid, date_field.value.strip(), w, selected_hive)
            close_dialog(dialog)
            on_save()

        dialog = ft.AlertDialog(
            title=ft.Text("Редактировать замер" if is_edit else "Новый замер"),
            content=ft.Column([date_row, weight_field, hive_dropdown, attached_note], tight=True, spacing=8),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    def confirm_delete_measurement(aid, sid, mid, on_confirm):
        def do_del(e):
            storage.delete_measurement(aid, sid, mid)
            close_dialog(dlg)
            on_confirm()

        dlg = ft.AlertDialog(
            title=ft.Text("Удалить замер?"),
            content=ft.Text("Это действие нельзя отменить."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dlg)),
                ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_del),
            ])
        open_dialog(dlg)

    # ================= SCALE QUICK ACTIONS =================
    def open_scale_quick_actions(aid, sid):
        scale = storage.get_scale(aid, sid)
        if not scale: return

        is_attached = bool(scale.get("attached_hive_id"))

        def stats_action(e):
            close_dialog(dialog)
            show_scale_stats(aid, sid)

        def detach_action(e):
            close_dialog(dialog)
            hives = storage.list_hives(aid)
            hive = next((h for h in hives if h["id"] == scale.get("attached_hive_id")), None)
            if hive:
                storage.update_scale(aid, sid, {
                    "attached_hive_id": None,
                    "x": hive.get("x", 0.3),
                    "y": min(0.95, hive.get("y", 0.4) + 0.2),
                })
            else:
                storage.update_scale(aid, sid, {"attached_hive_id": None})
            show_apiary(aid)

        def rename_action(e):
            close_dialog(dialog)
            tf = ft.TextField(label="Название весов", value=scale.get("name", "Весы"), autofocus=True)

            def do_rename(ev):
                new_name = tf.value.strip() or "Весы"
                storage.update_scale(aid, sid, {"name": new_name})
                close_dialog(rdialog)
                show_apiary(aid)

            rdialog = ft.AlertDialog(
                title=ft.Text("Переименовать весы"),
                content=ft.Column([tf], tight=True),
                actions=[
                    ft.TextButton("Отмена", on_click=lambda ev: close_dialog(rdialog)),
                    ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=do_rename),
                ])
            open_dialog(rdialog)

        def add_measurement_action(e):
            close_dialog(dialog)
            open_measurement_dialog(aid, sid, None, None, None, lambda: show_scale_stats(aid, sid))

        def delete_action(e):
            close_dialog(dialog)
            def do_del(ev):
                storage.delete_scale(aid, sid)
                close_dialog(ddel)
                show_apiary(aid)

            ddel = ft.AlertDialog(
                title=ft.Text("Удалить весы?"),
                content=ft.Text("Все замеры этих весов будут удалены."),
                actions=[
                    ft.TextButton("Отмена", on_click=lambda ev: close_dialog(ddel)),
                    ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_del),
                ])
            open_dialog(ddel)

        items = []
        if is_attached:
            items.append(ft.ListTile(
                leading=ft.Icon(Icons.LINK_OFF, color="#1976D2"),
                title=ft.Text("Открепить от улья"),
                subtitle=ft.Text("Затем перетащите к другому улью", size=11, color="#666666"),
                on_click=detach_action))
        items.append(ft.ListTile(leading=ft.Icon(Icons.SHOW_CHART), title=ft.Text("Статистика и график"), on_click=stats_action))
        items.append(ft.ListTile(leading=ft.Icon(Icons.ADD), title=ft.Text("Добавить замер"), on_click=add_measurement_action))
        items.append(ft.ListTile(leading=ft.Icon(Icons.EDIT), title=ft.Text("Переименовать"), on_click=rename_action))
        items.append(ft.ListTile(leading=ft.Icon(Icons.DELETE, color=DANGER), title=ft.Text("Удалить весы", color=DANGER), on_click=delete_action))

        title_suffix = " (прикреплены к улью)" if is_attached else ""
        dialog = ft.AlertDialog(
            title=ft.Text(f"Весы «{scale.get('name', 'Весы')}»{title_suffix}"),
            content=ft.Column(items, tight=True, spacing=0),
            actions=[ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog))])
        open_dialog(dialog)

    def open_scale_dialog(aid):
        name_field = ft.TextField(label="Название весов", value=f"Весы {len(storage.list_scales(aid)) + 1}", autofocus=True)

        def save(e):
            name = name_field.value.strip() or "Весы"

            def do_save():
                storage.add_scale(aid, {"name": name})
                close_dialog(dialog)
                show_apiary(aid)

            confirm_action("Новые весы", f"Создать весы '{name}'?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text("Новые весы"),
            content=ft.Column([name_field], tight=True),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Создать", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    # ================= CALENDAR (ОБЫЧНАЯ СЕТКА) =================
    def show_calendar(aid):
        nonlocal current_aid, current_hid
        current_aid = aid
        current_hid = None
        apiary = storage.get_apiary(aid)
        if not apiary: return show_welcome()

        page.bgcolor = "#FFFFFF"
        body.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        body.controls.clear()

        body.controls.append(ft.Row([
            ft.IconButton(Icons.ARROW_BACK, on_click=lambda e: show_apiary(aid)),
            ft.Text("Календарь", size=22, weight=ft.FontWeight.BOLD, expand=True),
            ft.IconButton(Icons.ADD_CIRCLE, icon_color=HONEY, icon_size=36, tooltip="Добавить событие",
                          on_click=lambda e: open_event_dialog(aid, default_date=cal_state["selected"])),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        def change_month(delta):
            cal_state["month"] += delta
            if cal_state["month"] > 12:
                cal_state["month"] = 1
                cal_state["year"] += 1
            elif cal_state["month"] < 1:
                cal_state["month"] = 12
                cal_state["year"] -= 1
            show_calendar(aid)

        month_header = ft.Row([
            ft.IconButton(Icons.CHEVRON_LEFT, on_click=lambda e: change_month(-1)),
            ft.Text(f"{MONTHS_RU[cal_state['month'] - 1]} {cal_state['year']}", size=18, weight=ft.FontWeight.BOLD, width=150, text_align=ft.TextAlign.CENTER),
            ft.IconButton(Icons.CHEVRON_RIGHT, on_click=lambda e: change_month(1)),
        ], alignment=ft.MainAxisAlignment.CENTER)

        weekdays = ft.Row([
            ft.Text(d, size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, expand=1, color="#666666")
            for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]])

        events = storage.list_events(aid)
        event_dates = set(ev.get("date") for ev in events if ev.get("date"))

        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdayscalendar(cal_state["year"], cal_state["month"])

        grid_rows = []
        for week in month_days:
            row = []
            for day in week:
                if day == 0:
                    row.append(ft.Container(expand=1, height=44))
                else:
                    day_str = f"{cal_state['year']}-{cal_state['month']:02d}-{day:02d}"
                    is_selected = (day_str == cal_state["selected"])
                    has_event = (day_str in event_dates)

                    cell = ft.Column([
                        ft.Text(str(day), size=14, color="#FFFFFF" if is_selected else "#000000",
                                weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.NORMAL),
                        ft.Container(width=4, height=4, bgcolor=HONEY if has_event and not is_selected else "transparent", border_radius=2),
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2)

                    def on_day_click(e, ds=day_str):
                        cal_state["selected"] = ds
                        show_calendar(aid)

                    row.append(ft.Container(
                        content=cell, expand=1, height=44,
                        bgcolor=HONEY if is_selected else "transparent",
                        border=ft.border.all(1, "#E0E0E0") if not is_selected else None,
                        border_radius=8, on_click=on_day_click, alignment=ft.alignment.center))
            grid_rows.append(ft.Row(row, spacing=4))

        calendar_view = ft.Container(
            bgcolor=SOFT_YELLOW, border_radius=12, padding=12,
            content=ft.Column([month_header, weekdays, ft.Column(grid_rows, spacing=4)], spacing=8))
        
        body.controls.append(calendar_view)

        sel_date_dt = datetime.strptime(cal_state["selected"], "%Y-%m-%d")
        date_label = f"{sel_date_dt.day} {MONTHS_RU[sel_date_dt.month - 1]} {sel_date_dt.year}"

        body.controls.append(ft.Row([
            ft.Text(f"События на {date_label}", size=16, weight=ft.FontWeight.BOLD, expand=True),
            ft.Button("Назначить", icon=Icons.ADD, on_click=lambda e: open_event_dialog(aid, default_date=cal_state["selected"])),
        ]))

        day_events = [ev for ev in events if ev.get("date") == cal_state["selected"]]
        day_events.sort(key=lambda ev: ev.get("time", ""))

        if not day_events:
            body.controls.append(ft.Container(
                content=ft.Column([
                    ft.Icon(Icons.EVENT_NOTE, size=40, color="#CCCCCC"),
                    ft.Text("На этот день событий нет", color="#666666"),
                    ft.Button("Добавить событие", icon=Icons.ADD, on_click=lambda e: open_event_dialog(aid, default_date=cal_state["selected"])),
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20, alignment=ft.alignment.center, bgcolor="#F9F9F9", border_radius=12))
        else:
            ev_col = ft.Column(spacing=8)
            for ev in day_events:
                ev_col.controls.append(event_card(aid, ev))
            body.controls.append(ev_col)

        scrollable_content = ft.Column(controls=body.controls.copy(), scroll=ft.ScrollMode.AUTO, expand=True)
        body.controls.clear()
        body.controls.append(scrollable_content)
        page.update()

    def event_hives_text(aid, ev):
        hids = ev.get("hive_ids") or []
        if not hids: return "Все ульи"
        hives = storage.list_hives(aid)
        nums = []
        for h in hives:
            if h["id"] in hids:
                n = (h.get("number") or "").strip()
                nums.append(f"№{n}" if n else "Улей")
        return ", ".join(nums) if nums else "—"

    def event_card(aid, ev, hive_context=False):
        dt = parse_event_dt(ev)
        overdue = dt and dt < datetime.now() and not ev.get("notified")
        done = ev.get("notified", False)
        status_color = "#4CAF50" if done else (DANGER if overdue else HONEY)
        phone = ev.get("phone") or ""

        buttons = [ft.IconButton(Icons.DELETE, icon_color=DANGER, icon_size=20, on_click=lambda e: confirm_delete_event(aid, ev["id"]))]
        if phone:
            buttons.append(ft.IconButton(Icons.SMS, icon_color=HONEY, icon_size=20, tooltip="Отправить SMS/WhatsApp", on_click=lambda e: show_sms_dialog(ev)))

        return ft.Container(
            bgcolor="#FFFFFF" if hive_context else SOFT_YELLOW, border_radius=12, padding=10,
            border=ft.border.all(1, status_color),
            content=ft.Column([
                ft.Row([
                    ft.Container(width=10, height=10, bgcolor=status_color, border_radius=5),
                    ft.Text(ev.get("title") or "Событие", size=15, weight=ft.FontWeight.BOLD, expand=True),
                ]),
                ft.Text(f"{ev.get('date', '')} {ev.get('time', '')}", size=12, color="#333333"),
                ft.Text(f"🐝 {event_hives_text(aid, ev)}", size=12, color="#666666"),
                ft.Text(ev.get("notes") or "", size=12, color="#666666") if ev.get("notes") else ft.Container(),
                ft.Text(f"📱 {phone}", size=12, color="#444444") if phone else ft.Container(),
                ft.Row(buttons, alignment=ft.MainAxisAlignment.END),
            ], spacing=3))

    def show_sms_dialog(ev):
        phone = ev.get("phone", "")
        text = f"{ev.get('title', '')} — {ev.get('date', '')} {ev.get('time', '')}"
        phone_digits = "".join(c for c in phone if c.isdigit() or c == "+")

        def open_sms(e):
            try: webbrowser.open(f"sms:{phone_digits}?body={quote(text)}")
            except Exception as ex: print(f"SMS error: {ex}")

        def open_whatsapp(e):
            digits = "".join(c for c in phone_digits if c.isdigit())
            try: webbrowser.open(f"https://wa.me/{digits}?text={quote(text)}")
            except Exception as ex: print(f"WhatsApp error: {ex}")

        def copy_phone(e):
            copy_to_clipboard(phone)
            phone_text.value = "Скопировано!"
            page.update()

        def copy_text(e):
            copy_to_clipboard(text)
            text_copy_status.value = "Скопировано!"
            page.update()

        phone_text = ft.Text(phone, size=13, selectable=True)
        text_copy_status = ft.Text("", size=11, color=HONEY)

        dlg = ft.AlertDialog(
            title=ft.Text("SMS / WhatsApp"),
            content=ft.Column([
                ft.Text("Автоматическая отправка SMS невозможна без внешнего сервиса. Используйте SMS-приложение или WhatsApp.", size=12, color="#666666"),
                ft.Text("Номер:", weight=ft.FontWeight.BOLD, size=13),
                phone_text,
                ft.Text("Текст:", weight=ft.FontWeight.BOLD, size=13),
                ft.Text(text, size=13, selectable=True),
                text_copy_status,
            ], tight=True, spacing=6),
            actions=[
                ft.TextButton("Копировать номер", on_click=copy_phone),
                ft.TextButton("Копировать текст", on_click=copy_text),
                ft.TextButton("Закрыть", on_click=lambda e: close_dialog(dlg)),
                ft.Button("WhatsApp", on_click=open_whatsapp, style=ft.ButtonStyle(bgcolor="#25D366", color="#FFFFFF")),
                ft.Button("SMS", on_click=open_sms, style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF")),
            ])
        open_dialog(dlg)

    # ================= APIARY/HIVE/EVENT DIALOGS =================
        def open_create_apiary():
        default_name = f"Пасека {len(storage.list_apiaries()) + 1}"
        name_field = ft.TextField(label="Название", value=default_name, autofocus=True)

        def save(e):
            name = name_field.value.strip() or default_name
            def do_save():
                try:
                    # Пытаемся создать пасеку
                    storage.create_apiary(name)
                    
                    # Пытаемся закрыть старое окно
                    close_dialog(dialog)
                    
                    # Перерисовываем главный экран
                    show_welcome()
                except Exception as ex:
                    # Если что-то пошло не так — показываем окно с ошибкой
                    err_dlg = ft.AlertDialog(
                        title=ft.Text("Ошибка создания"),
                        content=ft.Text(f"Детали: {ex}\n\nПопробуйте перезапустить приложение."),
                        actions=[ft.TextButton("OK", on_click=lambda e: close_dialog(err_dlg))]
                    )
                    open_dialog(err_dlg)

            confirm_action("Создание пасеки", f"Создать пасеку '{name}'?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text("Создать пасеку"),
            content=ft.Column([name_field], tight=True),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Создать", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    def open_add_menu(aid):
        def create_hive(e):
            close_dialog(dialog)
            open_hive_dialog(aid)

        def create_scale(e):
            close_dialog(dialog)
            open_scale_dialog(aid)

        def add_tier(e):
            close_dialog(dialog)
            choose_hive_for_tier(aid)

        hive_card = ft.Container(
            width=130, height=160, padding=12, border_radius=14, bgcolor=SOFT_YELLOW, border=ft.border.all(2, HONEY),
            on_click=create_hive, ink=True,
            content=ft.Column([
                mini_hive_preview(w=80, main_h=50, families=2, color=WOOD_LIGHT, number="новый"),
                ft.Container(height=6),
                ft.Text("Новый улей", size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4, tight=True))

        scale_card = ft.Container(
            width=130, height=160, padding=12, border_radius=14, bgcolor=SOFT_YELLOW, border=ft.border.all(2, HONEY),
            on_click=create_scale, ink=True,
            content=ft.Column([
                ft.Container(height=50, alignment=ft.alignment.center, content=build_scale_visual(90, 30, "0.0 кг", SCALE_DEFAULT_COLOR)),
                ft.Container(height=6),
                ft.Text("Новые весы", size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4, tight=True))

        tier_card = ft.Container(
            width=130, height=160, padding=12, border_radius=14, bgcolor=SOFT_YELLOW, border=ft.border.all(2, HONEY),
            on_click=add_tier, ink=True,
            content=ft.Column([
                mini_tier_preview(w=80, color=WOOD_LIGHT),
                ft.Container(height=6),
                ft.Text("Доп. ярус", size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4, tight=True))

        dialog = ft.AlertDialog(
            title=ft.Text("Что добавить?"),
            content=ft.Row([hive_card, scale_card, tier_card], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            actions=[ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog))])
        open_dialog(dialog)

    def choose_hive_for_tier(aid):
        hives = storage.list_hives(aid)
        if not hives:
            dlg = ft.AlertDialog(
                title=ft.Text("Нет ульев"),
                content=ft.Text("Сначала добавьте хотя бы один улей."),
                actions=[ft.TextButton("OK", on_click=lambda e: close_dialog(dlg))])
            open_dialog(dlg)
            return

        def add_to(hid):
            def do_add():
                storage.add_tier(aid, hid)
                close_dialog(dialog)
                show_apiary(aid)
            confirm_action("Добавление яруса", "Добавить новый ярус к этому улью?", do_add)

        cards = []
        for h in hives:
            fam = safe_int(h.get("families"), 0)
            col = h.get("color") or WOOD_LIGHT
            tiers_count = len(h.get("tiers") or [])
            hive_number = (h.get("number") or "").strip()
            display_number = hive_number if hive_number else "Улей"

            cards.append(ft.Container(
                width=130, height=150, padding=12, border_radius=12, bgcolor=SOFT_YELLOW, border=ft.border.all(2, HONEY),
                on_click=lambda e, hid=h["id"]: add_to(hid), ink=True,
                content=ft.Column([
                    mini_hive_preview(w=80, main_h=46, families=fam, color=col, number=hive_number, tiers=min(tiers_count, 3)),
                    ft.Container(height=2),
                    ft.Text(display_number, size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    ft.Text(f"ярусов: {tiers_count}", size=10, color="#666666"),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=2, tight=True)))

        grid = ft.GridView(expand=True, max_extent=140, spacing=10, run_spacing=10, child_aspect_ratio=0.85, controls=cards)

        dialog = ft.AlertDialog(
            title=ft.Text("К какому улью добавить ярус?"),
            content=ft.Container(content=grid, width=460, height=360),
            actions=[ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog))])
        open_dialog(dialog)

    def open_hive_dialog(aid, hive=None, hid=None, on_close=None):
        is_edit = hive is not None
        data = hive or {}

        number = ft.TextField(label="Номер улья", autofocus=True, value=data.get("number", ""))
        size = ft.TextField(label="Размер (ШxВ мм, напр. 600x500)", value=data.get("size", ""))
        frames = ft.TextField(label="Количество рамок", keyboard_type=ft.KeyboardType.NUMBER, value=data.get("frames", ""))
        notes = ft.TextField(label="Заметки", multiline=True, min_lines=2, value=data.get("notes", ""))

        def save(e):
            payload = {
                "number": number.value.strip(),
                "size": size.value.strip(),
                "frames": frames.value.strip(),
                "notes": notes.value.strip(),
            }

            def do_save():
                if is_edit:
                    storage.update_hive(aid, hid, payload)
                    close_dialog(dialog)
                    if on_close: on_close()
                    elif current_hid == hid: show_hive_detail(aid, hid)
                    else: show_apiary(aid)
                else:
                    storage.add_hive(aid, payload)
                    close_dialog(dialog)
                    if on_close: on_close()
                    else: show_apiary(aid)

            confirm_action("Сохранение", "Применить изменения улья?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text("Редактировать улей" if is_edit else "Новый улей"),
            content=ft.Container(
                width=380, height=520,
                content=ft.Column([number, size, frames, notes], tight=True, scroll=ft.ScrollMode.AUTO, spacing=8)),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    def confirm_delete_hive(aid, hid):
        def do_delete(e):
            storage.delete_hive(aid, hid)
            close_dialog(dialog)
            show_apiary(aid)

        dialog = ft.AlertDialog(
            title=ft.Text("Удалить улей?"),
            content=ft.Text("Это действие нельзя отменить."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_delete),
            ])
        open_dialog(dialog)

    def open_event_dialog(aid, event=None, eid=None, preselected_hives=None, default_date=None):
        is_edit = event is not None
        data = event or {}
        hives = storage.list_hives(aid)

        if data.get("hive_ids"):
            state = {"all": False, "hive_ids": list(data["hive_ids"])}
        elif preselected_hives:
            state = {"all": False, "hive_ids": list(preselected_hives)}
        else:
            state = {"all": True, "hive_ids": []}

        title = ft.TextField(label="Название", autofocus=True, value=data.get("title", ""))
        date_field = ft.TextField(label="Дата (ГГГГ-ММ-ДД)", value=data.get("date", default_date or ""), width=200)
        pick_date_btn = ft.IconButton(Icons.CALENDAR_MONTH, tooltip="Выбрать дату",
                                      on_click=lambda e: open_date_picker(lambda v: (setattr(date_field, "value", v), page.update())))
        date_row = ft.Row([date_field, pick_date_btn])

        time_field = ft.TextField(label="Время (ЧЧ:ММ)", value=data.get("time", ""), width=200)
        pick_time_btn = ft.IconButton(Icons.ACCESS_TIME, tooltip="Выбрать время",
                                      on_click=lambda e: open_time_picker(lambda v: (setattr(time_field, "value", v), page.update())))
        now_btn = ft.TextButton("Сейчас", on_click=lambda e: (
            setattr(date_field, "value", datetime.now().strftime("%Y-%m-%d")),
            setattr(time_field, "value", datetime.now().strftime("%H:%M")),
            page.update()))
        time_row = ft.Row([time_field, pick_time_btn, now_btn])

        phone = ft.TextField(label="Телефон (для SMS/WhatsApp)", value=data.get("phone", ""))
        notes = ft.TextField(label="Описание", multiline=True, min_lines=2, value=data.get("notes", ""))

        def apply_template(t):
            title.value = t
            page.update()

        template_chips = ft.Row(
            [ft.OutlinedButton(
                t, style=ft.ButtonStyle(color=HONEY, side=ft.BorderSide(1, HONEY),
                                        padding=ft.padding.symmetric(4, 10), text_style=ft.TextStyle(size=12)),
                on_click=lambda e, t=t: apply_template(t)) for t in TEMPLATES],
            wrap=True, spacing=6, run_spacing=6)

        all_box = ft.Checkbox(label="Все ульи", value=state["all"])
        hive_boxes = {}
        hive_col = ft.Column(spacing=0)
        for h in hives:
            hid_ = h["id"]
            num = (h.get("number") or "").strip()
            label = f"№{num}" if num else "Улей без номера"
            cb = ft.Checkbox(label=label, value=(hid_ in state["hive_ids"]), disabled=state["all"])
            hive_boxes[hid_] = cb
            hive_col.controls.append(cb)

        def on_all_change(e):
            state["all"] = all_box.value
            if state["all"]:
                state["hive_ids"] = []
                for cb in hive_boxes.values():
                    cb.value = False
                    cb.disabled = True
            else:
                for cb in hive_boxes.values():
                    cb.disabled = False
            page.update()

        def on_hive_change(hid_, e):
            cb = hive_boxes[hid_]
            if cb.value:
                if hid_ not in state["hive_ids"]: state["hive_ids"].append(hid_)
            else:
                if hid_ in state["hive_ids"]: state["hive_ids"].remove(hid_)
            state["all"] = False

        all_box.on_change = on_all_change
        for hid_, cb in hive_boxes.items():
            cb.on_change = lambda e, hid_=hid_: on_hive_change(hid_, e)

        hives_selector = ft.Column([
            ft.Text("К каким ульям относится:", size=13, weight=ft.FontWeight.BOLD),
            all_box,
            ft.Container(content=hive_col, padding=ft.padding.only(left=20)),
        ], spacing=2, tight=True) if hives else ft.Container()

        def save(e):
            if not title.value.strip():
                title.error_text = "Введите название"
                page.update()
                return
            payload = {
                "title": title.value.strip(),
                "date": date_field.value.strip(),
                "time": time_field.value.strip(),
                "phone": phone.value.strip(),
                "notes": notes.value.strip(),
                "hive_ids": [] if state["all"] else list(state["hive_ids"]),
            }

            def do_save():
                if is_edit:
                    payload["notified"] = False
                    storage.update_event(aid, eid, payload)
                else:
                    storage.add_event(aid, payload)
                close_dialog(dialog)
                if preselected_hives and len(preselected_hives) == 1:
                    show_hive_detail(aid, preselected_hives[0])
                else:
                    show_calendar(aid)

            confirm_action("Событие", "Сохранить это событие?", do_save)

        dialog = ft.AlertDialog(
            title=ft.Text("Редактировать событие" if is_edit else "Новое событие"),
            content=ft.Container(
                width=440, height=560,
                content=ft.Column([
                    ft.Text("Шаблоны:", size=13, weight=ft.FontWeight.BOLD),
                    template_chips,
                    title, date_row, time_row, phone, notes, hives_selector,
                ], tight=True, scroll=ft.ScrollMode.AUTO, spacing=8)),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Сохранить", style=ft.ButtonStyle(bgcolor=HONEY, color="#FFFFFF"), on_click=save),
            ])
        open_dialog(dialog)

    def confirm_delete_event(aid, eid):
        def do_delete(e):
            storage.delete_event(aid, eid)
            close_dialog(dialog)
            if current_hid: show_hive_detail(aid, current_hid)
            else: show_calendar(aid)

        dialog = ft.AlertDialog(
            title=ft.Text("Удалить событие?"),
            content=ft.Text("Это действие нельзя отменить."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: close_dialog(dialog)),
                ft.Button("Удалить", style=ft.ButtonStyle(bgcolor=DANGER, color="#FFFFFF"), on_click=do_delete),
            ])
        open_dialog(dialog)

    # ================= RESIZE =================
    _resize_state = {"timer": None, "last_size": (None, None)}

    def on_resize(e):
        new_size = (int(page.width or 0), int(page.height or 0))
        if new_size == _resize_state["last_size"]: return
        _resize_state["last_size"] = new_size

        if _resize_state["timer"] is not None:
            try: _resize_state["timer"].cancel()
            except Exception: pass

        def do_redraw():
            try:
                if current_hid and current_aid: show_hive_detail(current_aid, current_hid)
                elif current_aid: show_apiary(current_aid)
                else: show_welcome()
            except Exception as ex:
                print(f"resize redraw error: {ex}")

        t = threading.Timer(0.35, do_redraw)
        t.daemon = True
        _resize_state["timer"] = t
        t.start()

    page.on_resize = on_resize
    show_welcome()
    

if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
