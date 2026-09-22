"""Authored 320 x 240 layouts for color displays.

Use native scene bindings, with independent body, media and text geometry.
These rectangles never pass through the Photo layout or its scaling step.
"""
from copy import deepcopy
from tools.content.layouts import place, text_node, CENTER, RIGHT, WRAP
from tools.content.tsx import ContentError


def apply_layout(scenes, theme):
    style = theme['layout']
    if style == 'native':
        return deepcopy(scenes)
    # Graphite/Sunset reserve the bottom 30 pixels for transport chrome;
    # Aurora reserves 38 pixels at the left. Blueprint puts status below content.
    shells = {
        'default': ((12, 36, 296, 196), (0, 0, 320, 28)),
        'minimal': ((12, 40, 296, 192), (12, 6, 296, 26)),
        'graphite': ((16, 42, 288, 160), (0, 0, 320, 32)),
        'aurora': ((48, 40, 260, 192), (48, 6, 260, 28)),
        'sunset': ((16, 44, 288, 158), (0, 0, 320, 34)),
        'blueprint': ((12, 10, 296, 188), (0, 212, 320, 28)),
    }
    if style not in shells:
        raise ContentError('unsupported M25 theme layout')
    body, header = shells[style]
    x, y, w, h = body
    bottom = y + h
    fh = theme['font']['height']
    row = max(18, fh + 5)
    result = deepcopy(scenes)
    for scene in result:
        sid = scene['id'].rsplit('.', 1)[-1]
        nodes = scene['nodes']
        texts = [n for n in nodes if n['kind'] == 3]
        listing = next((n for n in nodes if n['kind'] in (6, 7, 8)), None)
        bars = [n for n in nodes if n['kind'] == 9]
        for node in nodes:
            if node['kind'] == 11:
                place(node, *header)
            elif style == 'minimal' and node['kind'] in (4, 5, 14):
                node['flags'] |= 2
        if listing:
            place(listing, x, y, w - (12 if bars else 0), h)
        # Fullscreen media owns its full native surface. Controls use their own
        # overlay header even when the theme normally has a bottom status bar.
        if sid in ('cover-flow', 'video-player'):
            continue
        if sid == 'video-controls':
            for node in nodes:
                if node['kind'] == 11:
                    place(node, 0, 0, 320, 28)
            continue
        if sid == 'photos-viewer':
            surface = next(n for n in nodes if n['kind'] == 15)
            place(surface, 0, 0 if style == 'blueprint' else 28, 320, 212)
            for node in nodes:
                if node['kind'] == 11:
                    place(node, 0, 212 if style == 'blueprint' else 0, 320, 28)
            continue
        if sid in ('music', 'music-queue', 'music-sound', 'themes', 'sleep-timer', 'clock-edit', 'video-settings'):
            footer = 34 if sid in ('sleep-timer', 'clock-edit') else 22
            listing['h'] = ((h - footer - 8) // row) * row
            for node in texts:
                place(node, x, bottom - footer, w, footer)
                node['flags'] = WRAP
        elif sid == 'music-search':
            place(texts[0], x, y, w, 22)
            place(listing, x, y + 30, w - 12, ((h - 60) // row) * row)
            place(texts[1], x, bottom - 24, w, 24)
            texts[1]['flags'] = WRAP
        elif sid in ('display', 'battery', 'shutdown'):
            place(listing, x, y, w, row * (2 if sid == 'shutdown' else 1))
            positions = [y + listing['h'] + 12, bottom - 46, bottom - 22]
            for node, top in zip(texts, positions):
                place(node, x, top, w, 22)
        elif sid == 'clock':
            place(texts[0], x, y, w, 38)
            texts[0]['flags'] = CENTER
            place(listing, x, y + 46, w - 12, 2 * row)
            place(texts[1], x, bottom - 38, w, 38)
            texts[1]['flags'] = WRAP
        elif sid == 'update':
            for i, node in enumerate(texts):
                place(node, x, y + i * 23, w, 21)
            place(listing, x, bottom - 32, w, 32)
        elif sid == 'now-playing':
            art = next(n for n in nodes if n['kind'] == 14)
            size = 80 if style in ('graphite', 'sunset') else 112
            place(art, x, y, size, size)
            tx = x + size + 12
            place(texts[0], tx, y, w - size - 12, 34)
            place(texts[1], tx, y + 40, w - size - 12, 34)
            texts[0]['flags'] = texts[1]['flags'] = WRAP
            place(texts[2], tx, y + 80, w - size - 12, 18)
            if style == 'aurora':
                place(art, x + (w - 48) // 2, y, 48, 48)
                for node, top, height in zip(texts, (y + 54, y + 92, y + 112), (34, 18, 18)):
                    place(node, x, top, w, height)
                    node['flags'] = CENTER | WRAP
            elif style == 'minimal':
                for node, top, height in zip(texts, (y + 8, y + 56, y + 104), (34, 34, 18)):
                    place(node, x, top, w, height)
            progress = next(n for n in nodes if n['kind'] == 10)
            place(progress, x, bottom - 38, w, 6)
            place(texts[3], x, bottom - 62, w, 18)
            texts[3]['deps'] |= 16
            nodes.extend([
                text_node(texts[0], 'Track elapsed', x, bottom - 22, (w - 12) // 2, 20),
                text_node(texts[0], 'Track remaining', x + (w + 12) // 2, bottom - 22, (w - 12) // 2, 20, RIGHT),
            ])
        elif sid == 'about':
            art = next(n for n in nodes if n['kind'] == 17)
            ah = h - 58
            aw = ah * 68 // 104
            place(art, x + (w - aw) // 2, y, aw, ah)
            for i, node in enumerate(texts):
                place(node, x, bottom - 46 + i * 24, w, 22)
                node['flags'] = CENTER
        elif sid == 'photos-grid':
            for node in texts:
                place(node, x + 8, y + h // 2 - 22, w - 24, 44)
                node['flags'] = CENTER | WRAP
        elif sid == 'video-output':
            place(listing, x, y + 12, w, row * 2)
            place(texts[0], x, bottom - 30, w, 24)
        elif scene['id'] == 'local.example.notes':
            place(texts[0], x, y, w, 22)
            half = (w - 12) // 2
            for node in nodes:
                if node['kind'] == 17:
                    place(node, x, y + 30, half, h - 114)
                elif node['kind'] == 15:
                    place(node, x + half + 12, y + 30, half, h - 114)
                elif node['kind'] == 12:
                    place(node, x, bottom - 72, w, 34)
                elif node['kind'] == 13:
                    place(node, x, bottom - 30, w, 30)
        for bar in bars:
            if listing:
                place(bar, x + w - 4, listing['y'], 4, listing['h'])
        scene['count'] = len(nodes)
    return result
