import time
from datetime import datetime, timedelta

from utils import parse_event_dt

try:
    from plyer import notification as plyer_notify
    HAS_PLYER = True
except Exception:
    HAS_PLYER = False


def show_system_notification(ev, apiary_name):
    title = f"🐝 {ev.get('title') or 'Событие'}"
    message = f"{apiary_name} · {ev.get('date')} {ev.get('time', '')}"
    if ev.get("notes"):
        message += f"\n{ev.get('notes')}"
    if HAS_PLYER:
        try:
            plyer_notify.notify(title=title, message=message,
                                app_name="Пчеловод", timeout=10)
            return
        except Exception as ex:
            print(f"plyer notify error: {ex}")
    print(f"NOTIFY: {title} — {message}")


def notification_loop(storage):
    while True:
        try:
            now = datetime.now()
            for a in storage.list_apiaries():
                aid = a["id"]
                for ev in list(storage.list_events(aid)):
                    if ev.get("notified"):
                        continue
                    dt = parse_event_dt(ev)
                    if dt is None:
                        continue
                    if now - timedelta(hours=1) < dt <= now + timedelta(minutes=1):
                        show_system_notification(ev, a.get("name", ""))
                        storage.mark_event_notified(aid, ev["id"])
        except Exception as ex:
            print(f"notification loop error: {ex}")
        time.sleep(30)