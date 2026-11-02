"""Writes the Finder window layout that make_dmg.sh puts into the disk image as .DS_Store.

Finder reads it when the DMG is opened: a fixed-size window with Relay.app on the left and the
Applications shortcut on the right, large icons, no toolbar or sidebar. Re-run it to change the layout:

    python3 -m pip install ds_store
    python3 scripts/make_dmg_layout.py scripts/dmg/DS_Store

The file is stored without the leading dot because .gitignore excludes .DS_Store.
"""
import sys
from ds_store import DSStore

WIDTH, HEIGHT = 540, 340
ICON_SIZE = 128
ITEMS = {'Relay.app': (150, 160), 'Applications': (390, 160)}  # icon centres inside the window

target = sys.argv[1]
with DSStore.open(target, 'w+') as store:
    store['.']['vSrn'] = ('long', 1)
    store['.']['bwsp'] = {
        'WindowBounds': '{{200, 140}, {%d, %d}}' % (WIDTH, HEIGHT),
        'ShowStatusBar': False,
        'ShowToolbar': False,
        'ShowPathbar': False,
        'ShowSidebar': False,
        'ContainerShowSidebar': False,
        'ShowTabView': False,
        'PreviewPaneVisibility': False,
        'SidebarWidth': 0,
    }
    store['.']['icvp'] = {
        'viewOptionsVersion': 1,
        'backgroundType': 0,
        'backgroundColorRed': 1.0,
        'backgroundColorGreen': 1.0,
        'backgroundColorBlue': 1.0,
        'gridOffsetX': 0.0,
        'gridOffsetY': 0.0,
        'gridSpacing': 100.0,
        'arrangeBy': 'none',
        'showIconPreview': True,
        'showItemInfo': False,
        'labelOnBottom': True,
        'textSize': 14.0,
        'iconSize': float(ICON_SIZE),
        'scrollPositionX': 0.0,
        'scrollPositionY': 0.0,
    }
    for name, (x, y) in ITEMS.items():
        store[name]['Iloc'] = (x, y)
print(target)
