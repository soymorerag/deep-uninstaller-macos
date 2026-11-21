#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deep Uninstaller para macOS
- Escanea residuos de apps (.app) por bundle ID y nombre.
- Modo dry-run por defecto: solo lista.
- Mueve selección a la Papelera (reversible) con confirmación.
- No toca rutas protegidas del sistema.
"""

from __future__ import annotations
import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
PROTECTED = [
    "/System", "/usr", "/bin", "/sbin", "/etc", "/var/db",
    "/private/var/db", "/Library/Extensions", "/Library/Kernels",
    "/Library/Frameworks", "/Library/Java", "/Library/Python",
    str(HOME / "Library/Keychains"), str(HOME / "Library/Mail"),
    str(HOME / "Library/Messages"), str(HOME / "Library/Safari"),
    str(HOME / "Library/Accounts"),
]
ALLOWED_ROOTS = [
    str(HOME / "Applications"), "/Applications",
    str(HOME / "Library"), "/Library",
    "/private/var/folders", str(HOME / ".Trash"),
]


def is_allowed(path: str) -> bool:
    p = os.path.realpath(path)
    for prot in PROTECTED:
        if p == prot or p.startswith(prot + "/"):
            return False
    for root in ALLOWED_ROOTS:
        if p == root or p.startswith(root + "/"):
            return True
    return False


def size_of_path(path: str) -> int:
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path) and not os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def bundle_id(app_path: Path) -> str | None:
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        return None
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        return data.get("CFBundleIdentifier")
    except Exception:
        return None


def list_apps() -> list[dict]:
    apps = []
    for d in [HOME / "Applications", Path("/Applications")]:
        if not d.exists():
            continue
        for item in sorted(d.iterdir()):
            if item.suffix == ".app" and item.is_dir():
                apps.append({"name": item.stem, "path": str(item), "bundleID": bundle_id(item)})
    # dedup by path
    seen = set()
    out = []
    for a in apps:
        if a["path"] in seen:
            continue
        seen.add(a["path"])
        out.append(a)
    out.sort(key=lambda x: x["name"].lower())
    return out


def search_terms(app: dict) -> list[str]:
    terms = set()
    bid = app.get("bundleID")
    if bid:
        terms.add(bid.lower())
        parts = bid.split(".")
        if parts:
            terms.add(parts[-1].lower())
    name = app["name"].lower()
    terms.add(name)
    terms.add(name.replace(" ", ""))
    terms.add(name.replace(" ", "-"))
    return [t for t in terms if len(t) >= 3]


def references_app_plist(plist_path: str, app: dict) -> bool:
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
    except Exception:
        return False
    try:
        blob = str(data).lower()
    except Exception:
        return False
    terms = search_terms(app)
    for t in terms:
        if t in blob:
            return True
    if app["path"].lower() in blob:
        return True
    return False


def pkg_receipts(app: dict) -> list[dict]:
    terms = search_terms(app)
    try:
        out = subprocess.check_output(["/usr/sbin/pkgutil", "--pkgs"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    results = []
    for line in out.splitlines():
        pkg = line.strip()
        if not pkg:
            continue
        low = pkg.lower()
        if any(t in low for t in terms):
            for suffix in (".plist", ".bom"):
                p = f"/private/var/db/receipts/{pkg}{suffix}"
                if os.path.exists(p):
                    results.append({"path": p, "kind": "PKG Receipt", "pkg": pkg})
    return results


def scan_residuals(app: dict) -> list[dict]:
    terms = search_terms(app)
    home = str(HOME)
    candidate_dirs = [
        (home + "/Library/Application Support", "Application Support"),
        (home + "/Library/Application Scripts", "Application Script"),
        (home + "/Library/Caches", "Cache"),
        (home + "/Library/Preferences", "Preference"),
        (home + "/Library/Preferences/ByHost", "Preference (ByHost)"),
        (home + "/Library/Logs", "Log"),
        (home + "/Library/Containers", "Container"),
        (home + "/Library/Group Containers", "Group Container"),
        (home + "/Library/Saved Application State", "Saved State"),
        (home + "/Library/WebKit", "WebKit"),
        (home + "/Library/HTTPStorages", "HTTP Storage"),
        (home + "/Library/Cookies", "Cookie"),
        (home + "/Library/Services", "Service"),
        (home + "/Library/QuickLook", "QuickLook"),
        ("/Library/Application Support", "Application Support"),
        ("/Library/Caches", "Cache"),
        ("/Library/Preferences", "Preference"),
        ("/Library/Logs", "Log"),
        (home + "/Library/LaunchAgents", "Launch Agent"),
        ("/Library/LaunchAgents", "Launch Agent"),
        ("/Library/LaunchDaemons", "Launch Daemon"),
    ]
    results = []
    seen = set()
    for d, kind in candidate_dirs:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            low = entry.lower()
            if not any(t in low for t in terms):
                continue
            full = os.path.join(d, entry)
            if not is_allowed(full):
                continue
            if os.path.islink(full):
                try:
                    target = os.readlink(full)
                    if not os.path.isabs(target):
                        target = os.path.join(os.path.dirname(full), target)
                    if not is_allowed(target):
                        continue
                except OSError:
                    continue
            if full in seen:
                continue
            seen.add(full)
            results.append({"path": full, "kind": kind, "size": size_of_path(full), "selected": True})

    # Scan /private/var/folders for caches (bounded, with timeout)
    try:
        for t in terms:
            proc = subprocess.run(
                ["find", "/private/var/folders", "-maxdepth", "6", "-iname", f"*{t}*", "-print"],
                capture_output=True, text=True, timeout=20,
            )
            for line in proc.stdout.splitlines():
                p = line.strip()
                if not p or not is_allowed(p):
                    continue
                if p in seen:
                    continue
                seen.add(p)
                results.append({"path": p, "kind": "Var Folder Cache", "size": size_of_path(p), "selected": True})
    except Exception:
        pass
    launch_dirs = [home + "/Library/LaunchAgents", "/Library/LaunchAgents", "/Library/LaunchDaemons"]
    for d in launch_dirs:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for entry in entries:
            if not entry.endswith(".plist"):
                continue
            full = os.path.join(d, entry)
            if full in seen:
                continue
            if not is_allowed(full):
                continue
            if references_app_plist(full, app):
                seen.add(full)
                results.append({"path": full, "kind": "Launch Item", "size": size_of_path(full), "selected": True})

    # the app itself
    app_path = app["path"]
    if is_allowed(app_path):
        if app_path not in seen:
            seen.add(app_path)
            results.append({"path": app_path, "kind": "Application", "size": size_of_path(app_path), "selected": True})

    # pkg receipts (not selected by default)
    for r in pkg_receipts(app):
        if r["path"] not in seen:
            seen.add(r["path"])
            results.append({"path": r["path"], "kind": r["kind"], "size": 0, "selected": False, "pkg": r.get("pkg")})

    results.sort(key=lambda x: x["path"])
    return results


def osascript(script: str) -> str:
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip()
    except Exception:
        return ""


def choose_from_list(items, prompt, title, default_items=None, multiple=False):
    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    as_list = "{" + ", ".join('"' + esc(x) + '"' for x in items) + "}"
    defaults = ""
    if default_items:
        defaults = " default items {" + ", ".join('"' + esc(x) + '"' for x in default_items) + "}"
    multi = "multiple selections allowed true" if multiple else "multiple selections allowed false"
    script = (
        'set AppleScript\'s text item delimiters to "|||"\n'
        f'set theChoice to choose from list {as_list} with prompt "{esc(prompt)}" with title "{esc(title)}" {multi}{defaults}\n'
        'if theChoice is false then return "false"\n'
        'return theChoice as string\n'
    )
    out = osascript(script)
    if out == "" or out == "false":
        return None
    chosen = [x for x in out.split("|||") if x != ""]
    # validate against items
    valid = [c for c in chosen if c in items]
    if not valid and chosen:
        # fallback exact
        valid = [c for c in items if c in chosen]
    return valid if valid else None


def display_dialog(text: str, title: str = "Deep Uninstaller", buttons: list[str] = ["OK"], default_button: str = "OK") -> str:
    btns = "{" + ", ".join('"' + b + '"' for b in buttons) + "}"
    script = f'display dialog "{text}" with title "{title}" buttons {btns} default button "{default_button}"'
    out = osascript(script)
    # output like "button returned:OK"
    if "button returned:" in out:
        return out.split("button returned:")[-1].strip()
    return out


def move_to_trash(paths: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    if not paths:
        return [], []
    # Use Finder to move to trash (native, handles permissions)
    items = ", ".join('POSIX file "' + p.replace('"', '\\"') + '"' for p in paths)
    script = f'tell application "Finder" to delete {{{items}}}'
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode == 0:
        return paths, []
    # fallback: move manually to ~/.Trash
    moved = []
    failed = []
    trash = HOME / ".Trash"
    trash.mkdir(exist_ok=True)
    for p in paths:
        try:
            dest = trash / Path(p).name
            # avoid collision
            if dest.exists():
                dest = trash / (Path(p).name + "_" + str(int(os.time())))
            shutil.move(p, str(dest))
            moved.append(p)
        except Exception as e:
            failed.append((p, str(e)))
    return moved, failed


def run_gui():
    apps = list_apps()
    if not apps:
        display_dialog("No se encontraron aplicaciones en /Applications ni ~/Applications.", "Deep Uninstaller")
        return
    app_names = [a["name"] for a in apps]
    # choose app
    selected = choose_from_list(app_names, "Selecciona la aplicación a desinstalar:", "Deep Uninstaller", multiple=False)
    if not selected:
        return
    app = next(a for a in apps if a["name"] == selected[0])

    # scan
    display_dialog(f"Escaneando residuos de {app['name']}...", "Deep Uninstaller", buttons=["OK"], default_button="OK")
    residuals = scan_residuals(app)
    if not residuals:
        display_dialog("No se encontraron residuos.", "Deep Uninstaller")
        return

    # build display items
    items = []
    for r in residuals:
        items.append(f"{r['path']}  [{r['kind']}]  ({human_size(r['size'])})")
    default_sel = [it for it, r in zip(items, residuals) if r.get("selected", True)]

    chosen = choose_from_list(items, "Selecciona los residuos a mover a la Papelera (dry-run: nada se borra hasta confirmar):",
                             "Residuos encontrados", default_items=default_sel, multiple=True)
    if chosen is None:
        display_dialog("Cancelado.", "Deep Uninstaller")
        return

    chosen_paths = []
    for it in chosen:
        # find corresponding residual
        idx = items.index(it)
        chosen_paths.append(residuals[idx]["path"])

    total = sum(next(r["size"] for r in residuals if r["path"] == p) for p in chosen_paths)
    ans = display_dialog(f"Se moverán {len(chosen_paths)} elementos ({human_size(total)}) a la Papelera.\n¿Continuar?",
                         "Confirmar", buttons=["Cancelar", "Mover a papelera"], default_button="Cancelar")
    if ans != "Mover a papelera":
        display_dialog("Cancelado. No se borró nada.", "Deep Uninstaller")
        return

    moved, failed = move_to_trash(chosen_paths)
    msg = f"Movidos a papelera: {len(moved)}."
    if failed:
        msg += f" Fallidos: {len(failed)}."
        # show first failure
        msg += "\n" + "\n".join(f"{p}: {e}" for p, e in failed[:5])
    display_dialog(msg, "Deep Uninstaller")

    # pkg receipts hint
    pkg_items = [r for r in residuals if r.get("pkg")]
    if pkg_items:
        pkgs = sorted(set(r["pkg"] for r in pkg_items))
        hint = "Para olvidar paquetes instalados (requiere sudo), ejecuta:\n" + "\n".join(f"sudo pkgutil --forget {p}" for p in pkgs)
        display_dialog(hint, "PKG Receipts")


def run_cli(args):
    apps = list_apps()
    if args.list:
        for a in apps:
            print(f"{a['name']}\t{a['bundleID']}\t{a['path']}")
        return
    if not args.app:
        print("Especifica --app \"Nombre\" o usa --gui", file=sys.stderr)
        sys.exit(1)
    matches = [a for a in apps if a["name"].lower() == args.app.lower() or args.app.lower() in a["name"].lower()]
    if not matches:
        print("App no encontrada", file=sys.stderr)
        sys.exit(1)
    app = matches[0]
    residuals = scan_residuals(app)
    if args.dry_run:
        for r in residuals:
            print(f"[{r['kind']}] {r['path']}  {human_size(r['size'])}  selected={r['selected']}")
        print(f"Total seleccionados: {human_size(sum(r['size'] for r in residuals if r['selected']))}")
        return
    if args.trash:
        paths = [r["path"] for r in residuals if r.get("selected", True)]
        if args.all:
            paths = [r["path"] for r in residuals]
        moved, failed = move_to_trash(paths)
        print(f"Movidos: {len(moved)} Fallidos: {len(failed)}")
        for p, e in failed:
            print("FAIL", p, e)
        return
    # default: print scan
    for r in residuals:
        print(f"[{r['kind']}] {r['path']}  {human_size(r['size'])}")


def main():
    parser = argparse.ArgumentParser(description="Deep Uninstaller para macOS")
    parser.add_argument("--gui", action="store_true", help="Abrir interfaz gráfica (diálogos nativos)")
    parser.add_argument("--list", action="store_true", help="Listar apps instaladas")
    parser.add_argument("--app", help="Nombre de la app")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Solo listar (por defecto)")
    parser.add_argument("--trash", action="store_true", help="Mover residuos seleccionados a papelera")
    parser.add_argument("--all", action="store_true", help="Incluir todos los residuos (incluidos no seleccionados)")
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        run_gui()
    else:
        run_cli(args)


if __name__ == "__main__":
    main()
