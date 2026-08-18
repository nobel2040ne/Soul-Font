"""{% vstatic %} — {% static %} with the file's modification time appended.

Django's dev server sends static files with a Last-Modified header and no ETag or
Cache-Control, so browsers apply a heuristic freshness window and reuse a cached copy
without revalidating. Editing retro.css then appears to do nothing until a hard reload.

Appending the mtime changes the URL whenever the file changes, so the browser fetches it
and never has to guess. In production, where the file does not change between deploys,
the URL is stable and stays cacheable.
"""
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def vstatic(path):
    url = static(path)
    try:
        full = finders.find(path)
        if full:
            return f'{url}?v={int(os.path.getmtime(full))}'
    except Exception:
        pass          # never let a cache-busting nicety break the page
    return url
