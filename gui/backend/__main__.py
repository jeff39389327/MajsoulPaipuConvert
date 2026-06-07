# -*- coding: utf-8 -*-
"""`python -m gui.backend <cmd>` 與凍結後 backend.exe 的進入點，皆委派給 cli.main。"""
from .cli import main

if __name__ == "__main__":
    main()
