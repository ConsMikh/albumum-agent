"""HTTP-клиент системы Albumum: запросы по контракту, ключ, темп, подтверждение, повтор."""

import errno
import hashlib
import json
import os
import re
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from albumum_cli import SUPPORTED_CONTRACT, __version__, harnesses, versions
from albumum_cli.output import (
    EXIT_ACTION,
    EXIT_AUTH,
    EXIT_CONTRACT,
    EXIT_ERROR,
    EXIT_RATE,
    note,
)

TIMEOUT = 30.0
RATE_WAITS = 3  # сколько раз ждать Retry-After на 429
MAX_WAIT_S = 65  # дольше одного ожидания не ждем
NET_RETRIES = 2  # повторы после обрыва связи (только чтение и запросы с ключом повтора)
CONTRACT_TTL_S = 600
DNS_TIMEOUT_S = 2.0  # проверка «есть ли сеть вообще» при отказе соединения
PROBE_HOST = "github.com"
CONTRACT_PATH = "/api/agent/contract"
CACHE_DIR = Path(os.environ.get("ALBUMUM_CACHE", "~/.cache/albumum")).expanduser()
CONFIRM_HEADER = "X-Albumum-Confirm"
IDEMPOTENCY_HEADER = "Idempotency-Key"
USER_AGENT = f"albumum-cli/{__version__}"

# Подменяются в тестах.
sleep = time.sleep
clock = time.time


class ApiError(Exception):
    """Отказ системы или невозможность до нее дойти. `status` None — ответа не было."""

    def __init__(self, status: int | None, code: str, reason: str, body: dict | None = None):
        super().__init__(reason)
        self.status = status
        self.code = code
        self.reason = reason
        self.body = body
        self.request_id: str | None = None  # ключ повтора создающего запроса

    def details(self) -> dict:
        """Подробности для вывода: поля тела, кроме кода и причины, и ключ повтора."""
        skip = {"code", "reason", "detail", "error", "status"}
        extra = {k: v for k, v in (self.body or {}).items() if k not in skip}
        if self.request_id:
            extra["request_id"] = self.request_id
        return extra


class InvalidAnswer(ApiError):
    """Система ответила, но ответ не годится (в том числе недопустимая версия набора)."""


class ContractMismatch(ApiError):
    """Контракт системы не тот, что понимает утилита: изменяющие команды не выполняются."""


AUTH_CODES = {
    "key_invalid",
    "key_expired",
    "key_revoked",
    "user_inactive",
    "ambiguous_auth",
    "forbidden_operation",
    "no_key",
    "url_mismatch",
    "key_malformed",
}

# Ключ Albumum: alb_<начало, 8 знаков>_<секрет, 43 знака> — как на сервере (agent/keys.py).
KEY_FORMAT = re.compile(r"alb_[a-z0-9]{8}_[A-Za-z0-9_-]{43}\Z")
KEY_MALFORMED = (
    "Ключ агента не похож на ключ Albumum (alb_…, 56 знаков) — скорее всего, при вставке "
    "попали лишние символы. Нажмите «Копировать» в окне ключа, выполните albumum init и на "
    "вопрос о ключе просто нажмите Enter — ключ возьмется из буфера обмена"
)


def check_key(token: str, *, strict: bool = False, received: int | None = None) -> None:
    """Ключ с управляющими символами не отправляется: прокси ответит голым 400, а не отказом
    системы. `strict` — полная сверка формата (при вводе в init). Ключ в сообщение не попадает."""
    bad = any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in token)
    if bad or (strict and not KEY_FORMAT.match(token)):
        # Только длина и начало «alb_» — по ним видно, что пришло; сам ключ не выводится.
        body = None
        if received is not None:
            body = {"received_length": received, "starts_with_alb": token.startswith("alb_")}
        raise ApiError(None, "key_malformed", KEY_MALFORMED, body)


ACTION_CONFLICTS = {"revision_mismatch", "unfilled_places", "format_affects_pages"}


def exit_code(error: ApiError) -> int:
    if isinstance(error, ContractMismatch):
        return EXIT_CONTRACT
    if error.status in (401, 403) or error.code in AUTH_CODES:
        return EXIT_AUTH
    if error.status == 429:
        return EXIT_RATE
    if error.status == 428:
        return EXIT_ACTION
    if error.status == 409 and (
        error.code in ACTION_CONFLICTS or error.code.startswith(("confirmation_", "idempotency_"))
    ):
        return EXIT_ACTION
    if error.status == 422 and error.code == "invalid_document":
        return EXIT_ACTION
    return EXIT_ERROR


LOCAL_HOSTS = {"localhost", "*.localhost", "127.0.0.1", "::1"}


def is_local(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return host in LOCAL_HOSTS or any(
        rule.startswith("*.") and host.endswith(rule[1:]) for rule in LOCAL_HOSTS
    )


def check_url(url: str, token: str | None) -> None:
    """Ключ агента по открытому http:// не отправляется, кроме локального адреса."""
    parts = urlsplit(url)
    if token and parts.scheme == "http" and not is_local(parts.hostname):
        raise ApiError(
            None,
            "insecure_url",
            f"Адрес {url} без шифрования (http://), а ключ агента задан: "
            "ключ не отправляется по открытому каналу. Используйте https://",
        )


def _cause_of(exc: BaseException) -> str | None:
    """«dns» — имя не разрешилось; «blocked» — соединение запрещено или сети нет (EPERM песочницы,
    ENETUNREACH, EHOSTUNREACH); «refused» — узел достижим, но порт закрыт; None — другой обрыв.
    httpx прячет причину в цепочке исключений."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, socket.gaierror):
            return "dns"
        if isinstance(seen, ConnectionRefusedError):
            return "refused"
        if isinstance(seen, PermissionError) or (
            isinstance(seen, OSError) and seen.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH)
        ):
            return "blocked"
        seen = seen.__cause__ or seen.__context__
    return None


def _resolves(host: str) -> bool:
    """Разрешается ли имя за DNS_TIMEOUT_S: getaddrinfo без тайм-аута, поэтому — в потоке."""
    result: list[bool] = []

    def lookup() -> None:
        try:
            socket.getaddrinfo(host, None)
            result.append(True)
        except (OSError, TimeoutError, UnicodeError):
            result.append(False)

    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    worker.join(DNS_TIMEOUT_S)
    return bool(result and result[0])


def classify_network(exc: httpx.TransportError, url: str) -> ApiError:
    """Обрыв связи: песочница харнесса без сети (`sandbox_no_network`) или прежний
    `network_error`. Код выхода у обоих прежний (1)."""
    plain = ApiError(None, "network_error", f"Нет связи с системой {url}: {exc}")
    cause = _cause_of(exc)
    if cause is None:
        return plain
    host = urlsplit(url).hostname
    # Ошибка DNS при живом DNS (адрес системы или github.com разрешается) — опечатка в адресе или
    # недоступное имя, а не песочница: CLAUDECODE задан в любом сеансе Claude Code.
    if cause == "dns" and ((host and _resolves(host)) or _resolves(PROBE_HOST)):
        return plain
    # Отказ соединения — узел достижим: внутри харнесса это скорее остановленная система, чем
    # песочница. Такой отказ идет к проверке DNS.
    harness = harnesses.running_inside() if cause != "refused" else None
    if harness is not None:
        advice = (
            f"Разрешите сеть: {harness.network_hint}"
            if harness.network_hint
            else "Разрешите сеть в настройках песочницы харнесса"
        )
        return ApiError(
            None,
            "sandbox_no_network",
            f"Похоже, харнесс {harness.title} запускает команды в песочнице без сети. {advice}",
        )
    if cause != "dns" and ((host and _resolves(host)) or _resolves(PROBE_HOST)):
        return plain
    return ApiError(
        None,
        "sandbox_no_network",
        "Нет сети внутри среды агента. Если харнесс запускает команды в песочнице, "
        f"разрешите ей доступ к сети или к адресу {url}",
    )


def get_version(url: str, transport=None) -> dict:
    """GET /api/system/version — публичный путь: ключ агента на него не отправляется."""
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as http:
            response = http.get(f"{url}/api/system/version", headers=headers)
    except httpx.TransportError as exc:
        raise classify_network(exc, url) from None
    except httpx.HTTPError as exc:
        raise ApiError(None, "network_error", f"Нет связи с системой {url}: {exc}") from None
    if response.status_code != 200:
        raise _refusal(response)
    try:
        body = response.json()
        info = {
            "version": str(body["version"]),
            "agent_contract": int(body["agent_contract"]),
            "agent_kit": str(body["agent_kit"]).removeprefix("v"),
        }
    except (ValueError, KeyError, TypeError):
        raise InvalidAnswer(
            200, "invalid_answer", f"Система {url} ответила не так, как ждет утилита"
        ) from None
    return info


def _refusal(response: httpx.Response) -> ApiError:
    """Отказ из ответа: тело `{code, reason, …}` — как есть, иначе — сырой ответ (код выхода 1)."""
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("code"), str):
        reason = body.get("reason") or body.get("detail") or f"Система ответила кодом {status}"
        return ApiError(status, body["code"], str(reason), body)
    raw = body if body is not None else response.text[:4000]
    # Адрес запроса и сервер-отправитель: по ним видно, кто ответил — система, служба входа или
    # промежуточный прокси (ключа в адресе нет, он только в заголовке).
    details = {
        "raw": raw,
        "url": str(response.request.url.copy_with(query=None)),
        "server": response.headers.get("server"),
    }
    return ApiError(status, "unexpected_response", f"Система ответила кодом {status}", details)


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After")
    if value is None:
        try:
            value = response.json().get("retry_after")
        except (ValueError, AttributeError):
            value = None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = MAX_WAIT_S
    return max(0.0, min(seconds, MAX_WAIT_S))


class ApiClient:
    def __init__(self, url: str, token: str, *, transport=None):
        self.url = url.rstrip("/")
        check_key(token)
        self.token = token
        self.transport = transport
        self._contract: dict | None = None
        self._warned: set[str] = set()

    # --- запрос ---

    def request(
        self,
        method: str,
        path: str,
        *,
        params=None,
        json=None,
        data=None,
        files=None,
        confirm: str | None = None,
        idempotency_key: str | None = None,
        save_to: Path | None = None,
    ):
        """Один запрос с ключом. 429 — ожидание Retry-After (до трех раз); обрыв связи
        повторяется только для GET и запросов с ключом повтора — тем же телом байт в байт."""
        check_url(self.url, self.token)
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT}
        if confirm:
            headers[CONFIRM_HEADER] = confirm
        if idempotency_key:
            headers[IDEMPOTENCY_HEADER] = idempotency_key
        content = None
        if json is not None:
            content = _json_bytes(json)
            headers["Content-Type"] = "application/json"
        method = method.upper()
        retryable = method == "GET" or bool(idempotency_key)
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self.transport) as http:
                built = http.build_request(
                    method,
                    self.url + path,
                    params=params,
                    content=content,
                    data=data,
                    files=files,
                    headers=headers,
                )
                if idempotency_key:
                    built.read()  # тело один раз: повтор шлет те же байты
                return self._send(http, built, retryable=retryable, save_to=save_to)
        except ApiError as error:
            error.request_id = idempotency_key
            raise

    def _send(self, http: httpx.Client, built: httpx.Request, *, retryable: bool, save_to):
        """Обрыв связи — и при отправке, и посреди тела ответа — повторяется только для
        повторяемых запросов; иначе `network_error`."""
        waits = broken = 0
        while True:
            try:
                response = http.send(built, stream=True)
                try:
                    if response.status_code == 429 and waits < RATE_WAITS:
                        response.read()
                        waits += 1
                        sleep(_retry_after(response))
                        continue
                    if not response.is_success:
                        response.read()
                        raise _refusal(response)
                    if save_to is not None:
                        return _save(response, Path(save_to))
                    response.read()
                    return _parse(response)
                finally:
                    response.close()
            except httpx.TransportError as exc:
                if retryable and broken < NET_RETRIES:
                    broken += 1
                    sleep(broken)
                    continue
                raise classify_network(exc, self.url) from None

    # --- контракт ---

    def contract(self) -> dict:
        """Контракт системы; кэш 10 минут в CACHE_DIR (ключ — адрес и версия утилиты)."""
        if self._contract is not None:
            return self._contract
        name = hashlib.sha256(f"{self.url}\n{__version__}".encode()).hexdigest()[:24]
        cache = CACHE_DIR / f"contract-{name}.json"
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            if 0 <= clock() - stored["fetched_at"] < CONTRACT_TTL_S:
                self._contract = stored["contract"]
                return self._contract
        except (OSError, ValueError, KeyError, TypeError):
            pass
        fetched = self.request("GET", CONTRACT_PATH)
        if not isinstance(fetched, dict) or not isinstance(fetched.get("operations"), list):
            raise InvalidAnswer(200, "invalid_answer", "Система отдала контракт не того вида")
        try:
            CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            text = json.dumps({"fetched_at": clock(), "contract": fetched}, ensure_ascii=False)
            fd = os.open(cache, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
                handle.write(text)
        except OSError:
            pass  # без кэша утилита работает, только чаще спрашивает контракт
        self._contract = fetched
        return fetched

    def check_contract(self, write: bool) -> None:
        """Другой номер контракта: изменяющая команда — ContractMismatch, читающая —
        предупреждение. Система ждет набор новее — предупреждение, команда выполняется."""
        found = self.contract()
        number = found.get("contract")
        if number != SUPPORTED_CONTRACT:
            message = (
                f"Контракт системы ({number}) не тот, что понимает утилита "
                f"({SUPPORTED_CONTRACT}): выполните `albumum update`."
            )
            if write:
                raise ContractMismatch(
                    None,
                    "contract_mismatch",
                    f"{message} Изменяющие команды до обновления не выполняются.",
                    {"contract": number, "supported_contract": SUPPORTED_CONTRACT},
                )
            self._warn(f"Предупреждение: {message} Чтение выполняется.")
        kit = str(found.get("kit") or "")
        if kit and not versions.is_release(kit):
            self._warn(versions.skipped(kit))
        elif versions.is_older(__version__, kit):
            self._warn(
                f"Предупреждение: набор агента {__version__} старше, чем ждет система ({kit}): "
                "выполните `albumum update`."
            )

    def _warn(self, text: str) -> None:
        """Одно предупреждение — один раз за запуск."""
        if text not in self._warned:
            self._warned.add(text)
            note(text)

    def op(self, op_id: str) -> dict:
        for operation in self.contract().get("operations", []):
            if operation.get("id") == op_id:
                return operation
        raise ContractMismatch(
            None,
            "contract_mismatch",
            f"Операции {op_id} нет в контракте системы: выполните `albumum update`.",
        )

    def run(self, op_id: str, *, path: dict | None = None, **kwargs):
        """Запрос операции контракта: адрес — из шаблона пути, изменяющая операция — только
        при совпавшем контракте; создающая (idempotent) сама получает ключ повтора."""
        given = kwargs.get("idempotency_key")
        check_request_id(given)
        operation = self.op(op_id)
        if given and not operation.get("idempotent"):
            raise ApiError(
                None,
                "usage",
                f"--request-id только у создающих операций; {op_id} повтор без дублей не держит",
            )
        self.check_contract(write=operation.get("area") == "write")
        url = fill_path(operation["path"], path or {})
        if operation.get("idempotent") and not given:
            kwargs["idempotency_key"] = uuid.uuid4().hex
        return self.request(operation["method"], url, **kwargs)


REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")


def check_request_id(value: str | None) -> None:
    """Ключ повтора — в формате сервера; проверяется до сети."""
    if value is not None and not REQUEST_ID_RE.fullmatch(value):
        raise ApiError(
            None,
            "usage",
            "--request-id: от 1 до 64 знаков — латинские буквы, цифры и «._:-»",
        )


def fill_path(template: str, values: dict) -> str:
    def put(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"нет параметра пути {name} для {template}")
        return quote(str(values[name]), safe="")

    return re.sub(r"\{(\w+)\}", put, template)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parse(response: httpx.Response):
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        raise InvalidAnswer(
            response.status_code, "invalid_answer", "Система ответила не JSON"
        ) from None


def _save(response: httpx.Response, target: Path) -> dict:
    """Файл ответа — во временный рядом, затем на место: обрыв не оставляет обрывка."""
    partial = target.with_name(target.name + ".part")
    size = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
                size += len(chunk)
        partial.replace(target)
    except httpx.TransportError:
        partial.unlink(missing_ok=True)
        raise  # повтор или network_error решает _send
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ApiError(None, "write_failed", f"Не удалось записать {target}: {exc}") from None
    saved = {
        "file": str(target.absolute()),  # относительный путь — от текущей папки процесса
        "size": size,
        "content_type": response.headers.get("content-type"),
    }
    for header, value in response.headers.items():
        if header.lower().startswith("x-albumum-"):
            saved[header.lower()] = value
    return saved
