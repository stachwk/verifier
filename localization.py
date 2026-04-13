#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-

import os
import json

DEFAULT_LANG = "en_US"
TRANSLATION_FILE = "localization.json"

_loaded_translations = None
_current_lang = None

def _load_translations():
    """
    Load translations from 'translations.json'.
    Select the dictionary based on the LANGUAGE environment variable.
    """
    global _loaded_translations, _current_lang
    if _loaded_translations is not None:
        return  # Already loaded

    lang_env = os.environ.get("LANGUAGE", "en_US.UTF-8")
    if lang_env.startswith("pl_PL"):
        _current_lang = "pl_PL"
    else:
        # Default to en_US (or when the prefix is unrecognized)
        _current_lang = "en_US"

    if not os.path.exists(TRANSLATION_FILE):
        # No translation file - use an empty dictionary
        _loaded_translations = {}
        return

    with open(TRANSLATION_FILE, "r", encoding="utf-8") as f:
        all_translations = json.load(f)
    
    # Select the dictionary for _current_lang, or an empty one
    _loaded_translations = all_translations.get(_current_lang, {})

def _t(msg_id: str, **kwargs) -> str:
    """
    Return a translated message.
    If it is missing from the dictionary, return "[<lang> MISSING] msg_id".
    """
    _load_translations()
    template = _loaded_translations.get(msg_id)
    if not template:
        return f"[{_current_lang} MISSING] {msg_id}"
    return template.format(**kwargs)

def current_language() -> str:
    """Return the current language code (for example 'en_US' or 'pl_PL')."""
    _load_translations()
    return _current_lang
