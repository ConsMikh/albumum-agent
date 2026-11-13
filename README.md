# Albumum для агента

Набор, с которым ИИ-агент (Claude Code, Codex, OpenCode и другие) работает с системой альбомов Albumum
от вашего имени: утилита командной строки `albumum` и скиллы, которые учат агента ею пользоваться.
Агент загружает снимки, собирает и верстает альбом, проверяет листы по изображению и публикует —
необратимое, массовое и меняющее доступ только после того, как покажет вам, что изменится, и вы
ответите «да».

Проще всего — скажите своему агенту:

> Установи набор Albumum по инструкции https://github.com/ConsMikh/albumum-agent

## Для человека: установка своими руками

**1. Откройте терминал.** macOS: Программы → Утилиты → Терминал. Windows: Пуск → «PowerShell». Linux:
программа «Терминал».

**2. Вставьте команду и нажмите Enter.**

macOS и Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/ConsMikh/albumum-agent/main/install.sh | sh
```

Windows:

```powershell
irm https://raw.githubusercontent.com/ConsMikh/albumum-agent/main/install.ps1 | iex
```

Команда сама поставит всё нужное и в конце напишет «Установлено: …». Если она просит открыть терминал
заново — закройте окно и откройте новое.

**3. Выпустите ключ агента** в редакторе Albumum: раздел «Агент» → «Новый ключ». Ключ показывается один
раз — скопируйте его.

**4. Подключите ключ и проверьте.** В том же окне терминала:

```sh
albumum init
albumum whoami
```

`albumum init` спросит адрес системы (Enter — адрес по умолчанию) и ключ: после «Копировать» в окне
ключа достаточно нажать Enter — ключ возьмется из буфера обмена; можно и вставить его (ввод скрыт, в
историю команд ключ не попадает). Утилита проверит ключ и сохранит. Ключ работает только с этим адресом. Чтобы отключить агента, отзовите ключ в разделе
«Агент».

## Если вы ИИ-агент

1. Определи ОС человека и выполни команду установки из шага 2 сам. Если клиент модели блокирует установщик
   (`curl … | sh`, `irm … | iex`), не обходи блокировку: покажи команду человеку, пусть выполнит её в своём
   окне терминала.
2. Покажи человеку итог установки. Код выхода не 0 — перескажи строку `albumum: …`, не обходи ошибку сам.
3. Попроси человека выпустить ключ (шаг 3) и в **своем** окне терминала выполнить `albumum init`
   (шаг 4). Сам `albumum init` не запускай и ключ в чат не принимай: ему нужен скрытый ввод человека.
   Затем проверь `albumum whoami`.
4. Если скиллы `albumum` в этом сеансе не видны — попроси человека открыть тебя заново. Дальше работай по
   скиллу `albumum`.

## Что ставится и куда

- [`uv`](https://docs.astral.sh/uv/), если его нет;
- утилита `albumum` (`uv tool install`) той версии, что в последнем выпуске зеркала;
- скиллы — в `~/.local/share/albumum/skills/` (Windows — `%LOCALAPPDATA%\albumum\skills\`), оттуда ссылками
  (Windows — копиями) в общий каталог `~/.agents/skills` и в собственный каталог каждого найденного харнесса,
  который общий не читает (перечень — в разделе «Харнессы»). Что подключено — `albumum harnesses`, подключить
  заново — `albumum harnesses --link`; для харнесса вне перечня см. «Ручное подключение».

Параметры установщика: `--version X.Y.Z` (или `ALBUMUM_VERSION`), `--from ПАПКА` (папка с
`albumum_cli-*.whl` и `skills/`), `--no-skills`. На Windows те же параметры задаются переменными
`ALBUMUM_VERSION`, `ALBUMUM_FROM`, `ALBUMUM_NO_SKILLS`.

<!-- harnesses:begin -->
## Харнессы

Установщик всегда подключает скиллы в общий каталог `~/.agents/skills`, а харнессам, которые его не читают, — еще и в их собственный каталог (если харнесс найден на компьютере). Что подключено у вас — `albumum harnesses`; найденным харнессам подключить скиллы заново — `albumum harnesses --link`.

| Харнесс | Собственный каталог скиллов | Читает общий каталог (по документации) | Куда ставит установщик |
|---|---|---|---|
| Claude Code | `~/.claude/skills` (Windows: `%USERPROFILE%\.claude\skills`) | нет | `~/.claude/skills` |
| Codex CLI | — | да | `~/.agents/skills` |
| OpenCode | `~/.config/opencode/skills` | да | `~/.agents/skills` |
| pi | `~/.pi/agent/skills` | да | `~/.agents/skills` |
| oh-my-pi | `~/.omp/agent/skills` | нет | `~/.omp/agent/skills` |
| Hermes Agent | `~/.hermes/skills` | нет | `~/.hermes/skills` |
| OpenClaw | `~/.openclaw/skills` | да | `~/.agents/skills` |
| Gemini CLI | `~/.gemini/skills` | да | `~/.agents/skills` |
| Antigravity CLI | `~/.gemini/antigravity-cli/skills` (Windows: `%USERPROFILE%\.gemini\antigravity-cli\skills`) | нет | `~/.gemini/antigravity-cli/skills` |
| GitHub Copilot CLI | `~/.copilot/skills` | да | `~/.agents/skills` |
| Cursor (cursor-agent) | `~/.cursor/skills` | да | `~/.agents/skills` |
| SourceCraft Code Assistant | `~/.codeassistant/skills` | да | `~/.agents/skills` |
| DeepSeek Harness | `~/.dsh/skills` | да | `~/.agents/skills` |

Колонка «Читает общий каталог» — по документации харнессов и сторонним описаниям, установкой не проверена; при сомнении смотрите строку своего харнесса в «По харнессам». Проверено ли подключение на вашей системе — таблица [HARNESSES.md](HARNESSES.md).

## Ручное подключение

Харнесса нет в списке или скиллы в нем не видны? Укажите ему каталог `~/.local/share/albumum/skills` (Windows — `%LOCALAPPDATA%\albumum\skills`) или скопируйте папки `albumum*` из него в каталог скиллов харнесса. Харнессу нужны запуск команд и чтение `SKILL.md`. После подключения перезапустите харнесс.

По харнессам:

- **Claude Code.** Положите ссылки (на Windows — копии) папок `albumum*` из `~/.local/share/albumum/skills` в `~/.claude/skills`.
- **Codex CLI.** Читает `~/.agents/skills` сам. При закрытой сети разрешите ее: `network_access = true` в разделе [sandbox_workspace_write] файла `~/.codex/config.toml`.
- **OpenCode.** Читает `~/.agents/skills` сам; собственный каталог — `~/.config/opencode/skills`.
- **pi.** Читает `~/.agents/skills` сам; собственный каталог — `~/.pi/agent/skills`.
- **oh-my-pi.** Установщик кладет ссылки в `~/.omp/agent/skills`. Вместо этого можно включить общий каталог: enableAgentsUser: true в блоке skills: файла `~/.omp/agent/config.yml`.
- **Hermes Agent.** Установщик кладет ссылки в `~/.hermes/skills`. Вместо этого можно добавить `~/.agents/skills` в skills.external_dirs файла `~/.hermes/config.yaml`.
- **OpenClaw.** Читает `~/.agents/skills` сам; собственный каталог — `~/.openclaw/skills`.
- **Gemini CLI.** Читает `~/.agents/skills` сам; собственный каталог — `~/.gemini/skills`.
- **Antigravity CLI.** Установщик кладет ссылки в `~/.gemini/antigravity-cli/skills`. Каталог `~/.gemini/skills` не трогайте: его читает и Gemini CLI, скиллы задвоятся.
- **GitHub Copilot CLI.** Читает `~/.agents/skills`; если скиллы не видны — ссылки в `~/.copilot/skills` или каталог в переменной `COPILOT_SKILLS_DIRS`.
- **Cursor (cursor-agent).** Читает `~/.agents/skills`; если скиллы не видны — ссылки в `~/.cursor/skills`.
- **SourceCraft Code Assistant.** Глобальный каталог скиллов расширения не подтвержден: если скиллы не видны, положите ссылки в `~/.codeassistant/skills` или в `.sourcecraft/skills/` репозитория.
- **DeepSeek Harness.** Читает `~/.agents/skills` (по стороннему описанию); если скиллы не видны — ссылки в `<dshHome>/skills`.
<!-- harnesses:end -->

## Команды

| Группа | Команды |
|---|---|
| Подключение | `albumum init`, `whoami`, `version`, `update`, `contract [--op ID]`, `schema`, `config set-url`, `call МЕТОД ПУТЬ` (запасной путь по контракту), `harnesses [--link]` (куда подключены скиллы) |
| Библиотека | `albumum library list / get / upload / image / original / trash / move / taken-at / usage / used-in`, `folders list / create / rename / delete` |
| Обработка файлов | `albumum library process / trim / poster / current / version-trash / version-file` |
| Корзина | `albumum trash list / restore / purge` |
| Альбомы | `albumum albums list`, `album create / get / set / format-check / spec / delete`, `catalog fonts / decorations / templates / formats` |
| Листы | `albumum pages add / trash / order / background / background-copy`, `page get / put / fill / template / delete / image` |
| Публикация | `albumum publication status / publish / revoke / withdraw / album`, `publication password set / clear` |

Справка по любой команде — `--help` (у основных команд — с примерами). `albums list`, `album set`, `pages add`, `catalog templates`
по умолчанию отвечают кратко, полный ответ — `--full`. Файлы JSON принимаются и с BOM (PowerShell 5.1). Команда из перечня подтверждений без `--confirm` печатает
предпросмотр с жетоном и выходит с кодом 2; с `--confirm ЖЕТОН` — выполняет. Создающие команды при
обрыве связи печатают `request_id`: повтор с `--request-id` не создаст дубль. Пароль альбома — скрытым
вводом или строкой stdin.

## Скиллы

| Скилл | О чем |
|---|---|
| `albumum` | вход: подключение, правила «всегда», коды выхода, обновление, к какому скиллу идти |
| `albumum-library` | загрузка папки, библиотека, каталоги, корзина |
| `albumum-album` | альбом, формат, стиль, листы, заготовки |
| `albumum-layout` | документ верстки листа, ошибки, конфликт ревизий, проверка по изображению листа |
| `albumum-publish` | публикация и доступ |
| `albumum-design` | оформление: места, спецификация оформления, свои украшения и рамки |

Настройки: флаг `--url` → переменные `ALBUMUM_URL`, `ALBUMUM_TOKEN` → файл `~/.config/albumum/config.toml`
(другой путь — `ALBUMUM_CONFIG`). Ключ привязан к адресу: ключ из файла — к адресу из файла,
`ALBUMUM_TOKEN` — к `ALBUMUM_URL`; для другого адреса ключ не отправляется (`url_mismatch`, код 3) —
выполните `albumum init` заново. `albumum config set-url` на другой адрес удаляет ключ из файла — после нее
тоже `albumum init`. Ключ аргументом команды не передается. Вывод — JSON в stdout, сообщения —
в stderr; ошибка — JSON `{error, code, status, …}`.

## Коды выхода

| Код | Значение |
|---|---|
| 0 | готово |
| 1 | прочая ошибка (нет адреса, нет связи, неверные аргументы `usage`, непонятный ответ; `library upload`, где не прошел ни один файл) |
| 2 | нужно действие: подтверждение человека (428, `confirmation_*`), конфликт ревизии, `unfilled_places`, `format_affects_pages`, `idempotency_*`, ошибки документа `invalid_document` |
| 3 | ключ или права: 401, 403 (`forbidden_operation`, в том числе отказ самой утилиты до сети), 400 `ambiguous_auth` (ключ вместе со входом), `no_key`, `url_mismatch`, `key_malformed` (в ключе лишние символы вставки — заново `albumum init`) |
| 4 | темп исчерпан после трех ожиданий `Retry-After` (429) |
| 5 | контракт системы не совпал: изменяющие команды не выполняются — `albumum update` |
| 6 | частично: главное сделано, часть элементов отклонена — `library upload` загрузил файлы (или они уже были), но часть в `rejected` |

## Выпуск

Версия набора совпадает с версией Albumum (файл `VERSION` основного репозитория). Зеркало
github.com/ConsMikh/albumum-agent обновляется только автоматически, из конвейера основного репозитория, на
теге `vX.Y.Z`; править его вручную не нужно.
