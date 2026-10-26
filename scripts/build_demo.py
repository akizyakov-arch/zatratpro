"""Build an isolated static preview; never includes DB data or credentials."""
from pathlib import Path
import argparse
import hashlib
import shutil

ROOT=Path(__file__).resolve().parent.parent


def build(destination):
    destination.mkdir(parents=True,exist_ok=True)
    static=ROOT/'app/web/static'
    html=(static/'index.html').read_text(encoding='utf-8')
    html=html.replace('/assets/app.css','./app.css').replace('/assets/app.js','./app.js')
    html=html.replace('<script src="./app.js" defer></script>', '<link rel="stylesheet" href="./demo.css" />\n    <script src="./demo.js" defer></script>\n    <script src="./app.js" defer></script>')
    html=html.replace('FIINOPS · Управление финансами','FIINOPS · Демонстрация интерфейса')
    (destination/'app.js').write_text((static/'app.js').read_text(encoding='utf-8').replace('Excel','CSV (демо)').replace('Защищённый доступ','Демонстрация'),encoding='utf-8')
    shutil.copyfile(static/'app.css',destination/'app.css')
    for name in ('demo.js','demo.css'):
        shutil.copyfile(ROOT/'demo'/name,destination/name)
    for name in ('app.js', 'app.css', 'demo.js', 'demo.css'):
        version=hashlib.sha256((destination/name).read_bytes()).hexdigest()[:12]
        html=html.replace(f'./{name}"',f'./{name}?v={version}"')
    (destination/'index.html').write_text(html,encoding='utf-8')
    (destination/'.nojekyll').touch()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
