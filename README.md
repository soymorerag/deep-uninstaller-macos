# Deep Uninstaller (macOS)

Desinstalador profundo para macOS que localiza una aplicación y sus residuos
(caches, preferencias, contenedores, launch agents, receipts de pkg, etc.) y los
mueve a la Papelera, de forma reversible, con modo dry-run por defecto.

## Uso

### App con GUI (diálogos nativos)

1. Abre `DeepUninstaller.app` (doble clic).
2. Selecciona la app a desinstalar.
3. Revisa la lista de residuos (preseleccionados).
4. Confirma para moverlos a la Papelera.

También puedes copiar `DeepUninstaller.app` a `/Applications`.

### Línea de comandos

```bash
# Listar apps instaladas
python3 deep_uninstaller.py --list

# Dry-run (solo lista) de una app
python3 deep_uninstaller.py --app "Blender" --dry-run

# Mover residuos seleccionados a la Papelera
python3 deep_uninstaller.py --app "Blender" --trash

# Incluir todos los residuos (incluso no seleccionados por defecto)
python3 deep_uninstaller.py --app "Blender" --trash --all
```

## Seguridad

- Modo dry-run por defecto: no se borra nada hasta confirmación explícita.
- Solo se permiten rutas bajo: `~/Applications`, `/Applications`, `~/Library`,
  `/Library`, `/private/var/folders`, `~/.Trash`.
- Rutas protegidas del sistema (`/System`, `/usr`, `/bin`, `/sbin`, `/etc`,
  `/var/db`, keychains, mail, etc.) nunca se tocan.
- El borrado real se hace moviendo a la Papelera (reversible). Para vaciar la
  Papelera, hazlo manualmente desde el Finder.
- Los receipts de paquetes (`pkgutil`) no se mueven automáticamente; se muestra
  el comando `sudo pkgutil --forget <id>` para ejecutar manualmente.

## Limitaciones

- No desinstala extensiones de kernel/sistema ni daemons que requieran privilegios
  especiales; se listan para acción manual.
- No garantiza "como si nunca se hubiera instalado": macOS puede conservar
  metadatos en bases de datos del sistema (Launch Services, Spotlight) fuera del
  alcance de este script. Puedes reconstruir Launch Services con:
  `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -kill -r -domain local -domain system -domain user`
- Login items se detectan pero no se remueven automáticamente.

## Requisitos

- macOS 12+
- Python 3 (incluido en macOS como `/usr/bin/python3`)

No requiere dependencias externas.
