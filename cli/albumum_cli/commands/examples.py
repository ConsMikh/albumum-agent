"""Примеры в справке основных команд (`--help`, раздел после флагов). Каждая строка — команда,
которую разбирает утилита (проверяет tests/test_help.py)."""

import argparse

EXAMPLES: dict[str, str] = {
    "harnesses": """\
albumum harnesses                # харнессы на компьютере и подключены ли скиллы
albumum harnesses --link         # подключить скиллы найденным харнессам
albumum harnesses --plain        # строки для установщика""",
    "library upload": """\
albumum library upload ~/Фото/Эльбрус --folder 12
albumum library upload IMG_0001.HEIC IMG_0002.MOV
albumum library upload --decoration рамка.png надпись.webp --wait   # свои украшения""",
    "library list": """\
albumum library list --from 2026-07-01 --to 2026-07-14 --all
albumum library list --folder 12 --kind photo
albumum library list --kind decoration     # свои украшения; all — все виды""",
    "library process": """\
albumum library process 501 --aspect 1:1 --wait
albumum library process 501 502 --flip h --rotate -1.5 --wait
albumum library process 501 --crop 0.1,0.1,0.8,0.8""",
    "library trim": """\
albumum library trim 610 --start 12.4 --end 52.4 --wait""",
    "library current": """\
albumum library current 501 9012""",
    "library version-trash": """\
albumum library version-trash 9012
albumum library version-trash 9012 9013 --confirm ЖЕТОН # только после явного «да» человека""",
    "library version-file": """\
albumum library version-file 9012 -o ~/albumum-work/501-v.jpg""",
    "library poster": """\
albumum library poster 9020 --at 12.5""",
    "library image": """\
albumum library image 501 --width 960 -o ~/albumum-work/501.webp""",
    "library taken-at": """\
albumum library taken-at 501 --at 2026-07-03T09:30          # в поясе автора (library usage, tz)
albumum library taken-at 501 --at 2026-07-03T09:30+05:00    # со смещением""",
    "albums list": """\
albumum albums list
albumum albums list --full""",
    "album create": """\
albumum album create --title "Эльбрус" --date 2026-07-03 --format 3:2 --sheet spread""",
    "album get": """\
albumum album get 7 -o ~/albumum-work/album.json""",
    "album spec": """\
albumum album spec 7 --page 41
albumum album spec 7 --thumbs -o ~/albumum-work/spec.json   # миниатюры — если автор разрешил""",
    "album set": """\
albumum album set 7 --title "Эльбрус, июль" --date 2026-07-03
albumum album set 7 --style ~/albumum-work/style.json
albumum album set 7 --cols 3 --col-gap 0.02 --margins safe    # сетка — только с согласия автора
albumum album set 7 --grid ~/albumum-work/grid.json --safe 0.05""",
    "pages background-copy": """\
albumum album get 7 -o ~/albumum-work/album.json
albumum pages background-copy 7 175 --from ~/albumum-work/album.json""",
    "catalog templates": """\
albumum catalog templates 7 --places 2
albumum catalog templates 7 --kind title --full""",
    "pages add": """\
albumum pages add 7 --template two-side --media 501,502,-,503
albumum pages add 7 --document ~/albumum-work/page.json --position 3
albumum pages add 7 --duplicate-of 41""",
    "pages order": """\
albumum pages order 7 40 42 41 43        # все листы; титульную можно не указывать""",
    "page get": """\
albumum page get 7 41 -o ~/albumum-work/page-41.json""",
    "page put": """\
albumum page put 7 41 ~/albumum-work/page-41.json""",
    "page fill": """\
albumum page fill 7 41 --place p1 --media 501
albumum page fill 7 41 --place p2 --media 502 --crop dx=0,dy=-0.4,scale=1.2
albumum page fill 7 41 --place p3 --decoration 812      # свое украшение
albumum page fill 7 41 --place p5 --text "Маше 5 лет!"
albumum page fill 7 41 --place p4 --sticker sticker-balloons""",
    "page template": """\
albumum page template 7 41 two-side --from ~/albumum-work/page-41.json --media 501,502""",
    "page image": """\
albumum page image 7 41 --width 800 -o ~/albumum-work/sheet-41.jpg""",
    "publication status": """\
albumum publication status 7""",
    "publication publish": """\
albumum publication publish 7                 # предпросмотр и confirm_token, код 2
albumum publication publish 7 --confirm ЖЕТОН # только после явного «да» человека""",
}


def _find(sub: argparse._SubParsersAction, words: list[str]) -> argparse.ArgumentParser:
    parser = sub.choices[words[0]]
    for word in words[1:]:
        nested = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        parser = nested.choices[word]
    return parser


def attach(sub: argparse._SubParsersAction) -> None:
    """Примеры — в справку команд; переводы строк в них сохраняются."""
    for command, text in EXAMPLES.items():
        parser = _find(sub, command.split())
        parser.epilog = "Примеры:\n" + "\n".join(f"  {line}" for line in text.splitlines())
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
