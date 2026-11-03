import json
import os
import shutil
import sys
import uuid
import threading
from datetime import datetime
from pathlib import Path

from constants import WOOD_LIGHT, SCALE_DEFAULT_COLOR
from utils import clamp


def get_data_dir() -> Path:
    # 1. Официальный путь Flet (работает в собранном .exe)
    base = os.getenv("FLET_APP_STORAGE_DATA")

    if base:
        root = Path(base)
    else:
        # 2. Если мы в режиме разработки (запуск python main.py)
        app_name = "Beekeeper"
        if sys.platform == "win32":
            # Используем %APPDATA% (C:\Users\Имя\AppData\Roaming\Beekeeper)
            base_dir = os.getenv("APPDATA") or os.path.expanduser("~")
            root = Path(base_dir) / app_name
        elif sys.platform == "darwin":  # macOS
            root = Path.home() / "Library" / "Application Support" / app_name
        else:  # Linux
            root = Path.home() / ".local" / "share" / app_name

    d = root / "apiaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Storage:
    def __init__(self):
        self.apiaries_root = get_data_dir()
        self.data_root = self.apiaries_root.parent
        self._lock = threading.Lock()
        self._hive_cache = {}
        self._hives_ids_cache = {}
        self._scale_cache = {}
        self._scales_ids_cache = {}
        self._events_cache = {}
        self._apiaries_cache = None
        self._photo_exists_cache = {}

    # ---------- helpers ----------
    def _invalidate_apiaries(self):
        self._apiaries_cache = None

    def _invalidate_hives_ids(self, aid):
        self._hives_ids_cache.pop(aid, None)

    def _dir(self, aid):
        return self.apiaries_root / f"apiary_{aid}"

    def _hive_file(self, aid, hid):
        return self._dir(aid) / "hives" / f"hive_{hid}.json"

    def _events_file(self, aid):
        return self._dir(aid) / "events.json"

    # ---------- hive ----------
    def _load_hive(self, aid, hid):
        key = (aid, hid)
        if key in self._hive_cache:
            return self._hive_cache[key]
        f = self._hive_file(aid, hid)
        if not f.exists():
            self._hive_cache[key] = None
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if data is not None and "families_data" not in data:
            data = self._migrate_families(data)
            try:
                self._save_hive(aid, hid, data)
            except Exception:
                pass
        self._hive_cache[key] = data
        return data

    def _migrate_families(self, hive):
        try:
            n = int(str(hive.get("families", "1")).strip())
        except Exception:
            n = 1
        n = max(0, n)
        hive["families_data"] = [
            {"id": uuid.uuid4().hex[:8],
             "queen_birth_year": None,
             "queen_age_at_add": None,
             "state": "",
             "notes": "",
             "created_at": datetime.now().isoformat()}
            for _ in range(n)
        ]
        hive["families"] = str(n)
        return hive

    def _save_hive(self, aid, hid, data):
        data["updated_at"] = datetime.now().isoformat()
        f = self._hive_file(aid, hid)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        self._hive_cache[(aid, hid)] = data

    def get_hive(self, aid, hid):
        return self._load_hive(aid, hid)

    # ---------- apiaries ----------
    def list_apiaries(self):
        if self._apiaries_cache is not None:
            return list(self._apiaries_cache)
        res = []
        for d in self.apiaries_root.iterdir():
            f = d / "apiary.json"
            if f.exists():
                try:
                    res.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
        res.sort(key=lambda a: a.get("created_at", ""))
        self._apiaries_cache = res
        return list(res)

    def get_apiary(self, aid):
        for a in self.list_apiaries():
            if a.get("id") == aid:
                return a
        return None

    def create_apiary(self, name):
        aid = uuid.uuid4().hex[:8]
        d = self._dir(aid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "hives").mkdir(exist_ok=True)
        data = {"id": aid, "name": name,
                "created_at": datetime.now().isoformat()}
        (d / "apiary.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self._invalidate_apiaries()
        return data

    # ---------- hives list ----------
    def list_hives(self, aid):
        ids = self._hives_ids_cache.get(aid)
        if ids is None:
            ids = set()
            d = self._dir(aid) / "hives"
            if d.exists():
                for f in d.glob("hive_*.json"):
                    stem = f.stem
                    if stem.startswith("hive_") and len(stem) > 5:
                        ids.add(stem[5:])
            self._hives_ids_cache[aid] = ids
        res = []
        for hid in ids:
            h = self._load_hive(aid, hid)
            if h is not None:
                res.append(h)
        res.sort(key=lambda h: (h.get("number") or "").zfill(4))
        return res

    def add_hive(self, aid, payload):
        d = self._dir(aid) / "hives"
        d.mkdir(parents=True, exist_ok=True)
        hid = uuid.uuid4().hex[:8]
        payload["id"] = hid
        payload.setdefault("families", "0")
        payload.setdefault("families_data", [])
        payload.setdefault("x", 0.5)
        payload.setdefault("y", 0.4)
        payload.setdefault("size", "600x500")
        payload.setdefault("photo", "")
        payload.setdefault("color", WOOD_LIGHT)
        payload.setdefault("tiers", [])
        payload["created_at"] = datetime.now().isoformat()
        (d / f"hive_{hid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self._hive_cache[(aid, hid)] = payload
        self._invalidate_hives_ids(aid)
        return payload

    def update_hive(self, aid, hid, payload):
        with self._lock:
            current = self._load_hive(aid, hid)
            if not current:
                return None
            current.update(payload)
            self._save_hive(aid, hid, current)
            return current

    def update_hive_position(self, aid, hid, nx, ny):
        with self._lock:
            current = self._load_hive(aid, hid)
            if not current:
                return
            current["x"] = round(clamp(nx, 0.0, 1.0), 4)
            current["y"] = round(clamp(ny, 0.0, 1.0), 4)
            self._save_hive(aid, hid, current)

    def delete_hive(self, aid, hid):
        hive = self._load_hive(aid, hid)
        if hive:
            if hive.get("photo"):
                p = self.data_root / Path(hive["photo"])
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            for tier in hive.get("tiers") or []:
                if tier.get("photo"):
                    p = self.data_root / Path(tier["photo"])
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
        f = self._hive_file(aid, hid)
        if f.exists():
            f.unlink()
        self._hive_cache.pop((aid, hid), None)
        self._invalidate_hives_ids(aid)
        with self._lock:
            events = list(self.list_events(aid))
            new_events = []
            for ev in events:
                hids = ev.get("hive_ids") or []
                if hids and hid in hids:
                    hids = list(hids)
                    hids.remove(hid)
                    if not hids:
                        continue
                    ev = dict(ev)
                    ev["hive_ids"] = hids
                new_events.append(ev)
            self._save_events(aid, new_events)

    # ---------- photos ----------
    def get_photo_abs(self, rel_path):
        return self.data_root / Path(rel_path)

    def photo_exists(self, rel_path):
        if not rel_path:
            return False
        cached = self._photo_exists_cache.get(rel_path)
        if cached is not None:
            return cached
        e = (self.data_root / Path(rel_path)).exists()
        self._photo_exists_cache[rel_path] = e
        return e

    def save_photo(self, aid, hid, src_path):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return None
            src = Path(src_path)
            ext = src.suffix.lower() or ".jpg"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dest = self._dir(aid) / "hives" / f"hive_{hid}_photo_{ts}{ext}"
            shutil.copy2(src, dest)
            if hive.get("photo"):
                old = self.data_root / Path(hive["photo"])
                if old.exists():
                    try:
                        old.unlink()
                    except Exception:
                        pass
            hive["photo"] = dest.relative_to(self.data_root).as_posix()
            self._save_hive(aid, hid, hive)
            return dest

    def clear_photo(self, aid, hid):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive or not hive.get("photo"):
                return
            p = self.data_root / Path(hive["photo"])
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
            hive["photo"] = ""
            self._save_hive(aid, hid, hive)

    # ---------- tiers ----------
    def add_tier(self, aid, hid):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return None
            tier = {
                "id": uuid.uuid4().hex[:8],
                "photo": "",
                "color": hive.get("color") or WOOD_LIGHT,
                "height": 150,
                "frames": "",
                "notes": "",
            }
            hive.setdefault("tiers", []).append(tier)
            self._save_hive(aid, hid, hive)
            return tier

    def update_tier(self, aid, hid, tid, payload):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return
            for t in hive.get("tiers") or []:
                if t["id"] == tid:
                    t.update(payload)
                    break
            self._save_hive(aid, hid, hive)

    # ---------- families ----------
    def get_families(self, aid, hid):
        hive = self._load_hive(aid, hid)
        if not hive:
            return []
        return list(hive.get("families_data") or [])

    def add_family(self, aid, hid, payload):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return None
            fam = {
                "id": uuid.uuid4().hex[:8],
                "queen_birth_year": payload.get("queen_birth_year"),
                "queen_age_at_add": payload.get("queen_age_at_add"),
                "state": payload.get("state", ""),
                "notes": payload.get("notes", ""),
                "created_at": datetime.now().isoformat(),
            }
            hive.setdefault("families_data", []).append(fam)
            hive["families"] = str(len(hive["families_data"]))
            self._save_hive(aid, hid, hive)
            return fam

    def update_family(self, aid, hid, fid, payload):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return None
            for f in hive.get("families_data") or []:
                if f["id"] == fid:
                    f.update(payload)
                    self._save_hive(aid, hid, hive)
                    return f
        return None

    def delete_family(self, aid, hid, fid):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return
            hive["families_data"] = [
                f for f in hive.get("families_data") or []
                if f["id"] != fid
            ]
            hive["families"] = str(len(hive["families_data"]))
            self._save_hive(aid, hid, hive)

    def delete_tier(self, aid, hid, tid):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return
            tiers = hive.get("tiers") or []
            for t in tiers:
                if t["id"] == tid and t.get("photo"):
                    p = self.data_root / Path(t["photo"])
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
            hive["tiers"] = [t for t in tiers if t["id"] != tid]
            self._save_hive(aid, hid, hive)

    def save_tier_photo(self, aid, hid, tid, src_path):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return None
            src = Path(src_path)
            ext = src.suffix.lower() or ".jpg"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dest = self._dir(aid) / "hives" / f"hive_{hid}_tier_{tid}_{ts}{ext}"
            shutil.copy2(src, dest)
            for t in hive.get("tiers") or []:
                if t["id"] == tid:
                    if t.get("photo"):
                        old = self.data_root / Path(t["photo"])
                        if old.exists():
                            try:
                                old.unlink()
                            except Exception:
                                pass
                    t["photo"] = dest.relative_to(self.data_root).as_posix()
                    break
            self._save_hive(aid, hid, hive)
            return dest

    def clear_tier_photo(self, aid, hid, tid):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return
            for t in hive.get("tiers") or []:
                if t["id"] == tid and t.get("photo"):
                    p = self.data_root / Path(t["photo"])
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                    t["photo"] = ""
                    break
            self._save_hive(aid, hid, hive)

    def set_hive_color(self, aid, hid, color, whole=False):
        with self._lock:
            hive = self._load_hive(aid, hid)
            if not hive:
                return
            hive["color"] = color
            if whole:
                for t in hive.get("tiers") or []:
                    t["color"] = color
            self._save_hive(aid, hid, hive)

    # ---------- scales ----------
    def _scales_dir(self, aid):
        return self._dir(aid) / "scales"

    def _scale_file(self, aid, sid):
        return self._scales_dir(aid) / f"scale_{sid}.json"

    def _load_scale(self, aid, sid):
        key = (aid, sid)
        if key in self._scale_cache:
            return self._scale_cache[key]
        f = self._scale_file(aid, sid)
        if not f.exists():
            self._scale_cache[key] = None
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            data = None
        self._scale_cache[key] = data
        return data

    def _save_scale(self, aid, sid, data):
        data["updated_at"] = datetime.now().isoformat()
        f = self._scale_file(aid, sid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        self._scale_cache[(aid, sid)] = data

    def list_scales(self, aid):
        ids = self._scales_ids_cache.get(aid)
        if ids is None:
            ids = set()
            d = self._scales_dir(aid)
            if d.exists():
                for f in d.glob("scale_*.json"):
                    stem = f.stem
                    if stem.startswith("scale_") and len(stem) > 6:
                        ids.add(stem[6:])
            self._scales_ids_cache[aid] = ids
        res = []
        for sid in ids:
            s = self._load_scale(aid, sid)
            if s is not None:
                res.append(s)
        res.sort(key=lambda s: s.get("name", ""))
        return res

    def get_scale(self, aid, sid):
        return self._load_scale(aid, sid)

    def add_scale(self, aid, payload):
        d = self._scales_dir(aid)
        d.mkdir(parents=True, exist_ok=True)
        sid = uuid.uuid4().hex[:8]
        payload["id"] = sid
        payload.setdefault("x", 0.3)
        payload.setdefault("y", 0.7)
        payload.setdefault("color", SCALE_DEFAULT_COLOR)
        payload.setdefault("measurements", [])
        payload.setdefault("attached_hive_id", None)
        payload["created_at"] = datetime.now().isoformat()
        (d / f"scale_{sid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self._scale_cache[(aid, sid)] = payload
        self._scales_ids_cache.pop(aid, None)
        return payload

    def update_scale(self, aid, sid, payload):
        with self._lock:
            current = self._load_scale(aid, sid)
            if not current:
                return None
            current.update(payload)
            self._save_scale(aid, sid, current)
            return current

    def update_scale_position(self, aid, sid, nx, ny):
        with self._lock:
            current = self._load_scale(aid, sid)
            if not current:
                return
            current["x"] = round(clamp(nx, 0.0, 1.0), 4)
            current["y"] = round(clamp(ny, 0.0, 1.0), 4)
            self._save_scale(aid, sid, current)

    def delete_scale(self, aid, sid):
        f = self._scale_file(aid, sid)
        if f.exists():
            f.unlink()
        self._scale_cache.pop((aid, sid), None)
        self._scales_ids_cache.pop(aid, None)

    def add_measurement(self, aid, sid, date_str, weight, hive_id=None):
        with self._lock:
            scale = self._load_scale(aid, sid)
            if not scale:
                return None
            m = {"id": uuid.uuid4().hex[:8],
                 "date": date_str,
                 "weight": float(weight),
                 "hive_id": hive_id}
            scale.setdefault("measurements", []).append(m)
            self._save_scale(aid, sid, scale)
            return m

    def update_measurement(self, aid, sid, mid, date_str, weight,
                           hive_id=None):
        with self._lock:
            scale = self._load_scale(aid, sid)
            if not scale:
                return
            for m in scale.get("measurements") or []:
                if m["id"] == mid:
                    m["date"] = date_str
                    m["weight"] = float(weight)
                    m["hive_id"] = hive_id
                    break
            self._save_scale(aid, sid, scale)

    def delete_measurement(self, aid, sid, mid):
        with self._lock:
            scale = self._load_scale(aid, sid)
            if not scale:
                return
            scale["measurements"] = [
                m for m in (scale.get("measurements") or [])
                if m["id"] != mid]
            self._save_scale(aid, sid, scale)

    # ---------- events ----------
    def list_events(self, aid):
        if aid in self._events_cache:
            return self._events_cache[aid]
        f = self._events_file(aid)
        if not f.exists():
            self._events_cache[aid] = []
            return []
        try:
            events = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            events = []
        self._events_cache[aid] = events
        return events

    def _save_events(self, aid, events):
        f = self._events_file(aid)
        f.write_text(json.dumps(events, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        self._events_cache[aid] = events

    def add_event(self, aid, payload):
        with self._lock:
            events = list(self.list_events(aid))
            eid = uuid.uuid4().hex[:8]
            payload["id"] = eid
            payload["notified"] = False
            payload["created_at"] = datetime.now().isoformat()
            events.append(payload)
            self._save_events(aid, events)
        return payload

    def update_event(self, aid, eid, payload):
        with self._lock:
            events = list(self.list_events(aid))
            for i, ev in enumerate(events):
                if ev["id"] == eid:
                    new_ev = dict(ev)
                    new_ev.update(payload)
                    new_ev["updated_at"] = datetime.now().isoformat()
                    events[i] = new_ev
                    self._save_events(aid, events)
                    return new_ev
        return None

    def delete_event(self, aid, eid):
        with self._lock:
            events = [ev for ev in self.list_events(aid) if ev["id"] != eid]
            self._save_events(aid, events)

    def mark_event_notified(self, aid, eid):
        self.update_event(aid, eid, {"notified": True})