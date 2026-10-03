"""Preserve ISO timestamp text after artifact-tool's automatic date coercion.

The workbook is authored/exported by artifact-tool. This narrowly removes the
escape apostrophe from literal timestamp string cells, leaving all other XLSX
parts, formulas, styles and numeric/date cells unchanged.
"""
import re
import sys
from pathlib import Path
from zipfile import ZipFile

p = Path(sys.argv[1])
temp = p.with_suffix('.xlsx.tmp')
with ZipFile(p) as src, ZipFile(temp, 'w') as dst:
    for info in src.infolist():
        data = src.read(info.filename)
        if info.filename == 'xl/sharedStrings.xml' or info.filename.startswith('xl/worksheets/sheet') and info.filename.endswith('.xml'):
            data = re.sub(rb"(<(?:\w+:)?(?:t|v)(?:\s[^>]*)?>)'(?=\d{4}-\d{2}-\d{2}T\d{2}:\d{2})",rb'\1',data)
        dst.writestr(info,data)
temp.replace(p)
