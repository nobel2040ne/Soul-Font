# pybo/signals.py
#
# Fonts (UserData rows) are now created explicitly — one per template upload in the
# `learning` view, or on demand in `result` — so we no longer auto-create a blank
# starter font when a User is created. A user simply starts with zero fonts.
#
# This module is intentionally left without receivers; it stays so the import in
# apps.py keeps working and there's an obvious home for future User signals.
