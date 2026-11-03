import flet as ft

from constants import WOOD_LIGHT, WOOD_DARK, ENTRANCE


def mini_hive_preview(w=100, main_h=60, families=2, color=WOOD_LIGHT,
                      number="", tiers=0):
    controls = []
    for _ in range(tiers):
        controls.append(ft.Container(width=w, height=8, bgcolor=color,
                                     border_radius=2,
                                     border=ft.border.all(1, WOOD_DARK)))
    controls.append(ft.Container(
        width=w, height=10, bgcolor=WOOD_DARK,
        border_radius=ft.border_radius.only(top_left=6, top_right=6)))
    fam_dots = ft.Row(
        [ft.Container(width=5, height=5, bgcolor=ENTRANCE, border_radius=3)
         for _ in range(families)],
        alignment=ft.MainAxisAlignment.CENTER, spacing=2)
    body_inner = ft.Column([
        ft.Text(number, size=9, color="#FFFFFF", weight=ft.FontWeight.BOLD)
            if number else ft.Container(height=0),
        ft.Container(expand=True),
        fam_dots,
    ], spacing=0, alignment=ft.MainAxisAlignment.START,
       horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    controls.append(ft.Container(
        width=w, height=main_h, bgcolor=color,
        border_radius=ft.border_radius.only(bottom_left=6, bottom_right=6),
        padding=3, content=body_inner))
    return ft.Column(controls, spacing=1, tight=True)


def mini_tier_preview(w=100, color=WOOD_LIGHT):
    return ft.Container(width=w, height=18, bgcolor=color, border_radius=3,
                        border=ft.border.all(1, WOOD_DARK))