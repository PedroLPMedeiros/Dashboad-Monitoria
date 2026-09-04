###################################################################
"""Cliente local para integração com o Mutant360."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter


BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Lê somente os metadados públicos do JWT para localizar o agente."""

    try:
        encoded_payload = token.split(".")[1]
        encoded_payload += "=" * (-len(encoded_payload) % 4)
        decoded = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _uuid_candidates(*payloads: Any) -> list[str]:
    """Encontra UUIDs prováveis do agente/supervisor sem expor o token."""

    found: list[tuple[int, int, str]] = []
    sequence = 0

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        nonlocal sequence

        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, (*path, str(key).lower()))
            return

        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child, path)
            return

        if not isinstance(value, str):
            return

        try:
            candidate = str(UUID(value.strip()))
        except (ValueError, AttributeError):
            return

        path_text = ".".join(path)
        if "agent" in path_text:
            priority = 0
        elif "supervisor" in path_text:
            priority = 1
        elif "user_id" in path_text or "userid" in path_text:
            priority = 2
        elif path and path[-1] == "id":
            priority = 3
        else:
            priority = 4

        found.append((priority, sequence, candidate))
        sequence += 1

    for payload in payloads:
        visit(payload)

    ordered: list[str] = []
    for _, _, candidate in sorted(found):
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


class MutantApiError(RuntimeError):
    """Erro seguro para apresentação na interface."""


@dataclass(frozen=True)
class UnitConfig:
    code: str
    label: str
    base_url: str
    campaign_ids: tuple[str, ...]


UNITS: tuple[UnitConfig, ...] = (
    UnitConfig(
        code="BRASILIA",
        label="Brasília",
        base_url="https://neoenergia.mutant360.com.br",
        campaign_ids=(
            "fc5c3e49-827a-4629-8760-b8c608ba1638",
            "dd84d593-336b-4c47-a537-9ecf5761f5b4",
        ),
    ),
    UnitConfig(
        code="COELBA",
        label="Coelba",
        base_url="https://neoenergiacoelba.mutant360.com.br",
        campaign_ids=(
            "3d94f4f5-be6d-4560-9ed9-89f754147cdf",
            "c1f11b05-077b-482b-91d2-dbfda2923382",
        ),
    ),
    UnitConfig(
        code="PERNAMBUCO",
        label="Pernambuco",
        base_url="https://neoenergiapernambuco.mutant360.com.br",
        campaign_ids=(
            "aad79933-7d1d-4267-aa01-29c57d40d6af",
            "87fcc6d3-f3a9-4a44-97b8-598eb23085fa",
        ),
    ),
    UnitConfig(
        code="ELEKTRO",
        label="Elektro",
        base_url="https://neoenergia.mutant360.com.br",
        campaign_ids=(
            "34d5afbb-4aae-4d23-9db4-01fa03e5aa8b",
            "77b922f9-9fe6-4590-83ae-8bea969e1251",
        ),
    ),
    UnitConfig(
        code="COSERN",
        label="Cosern",
        base_url="https://neoenergia.mutant360.com.br",
        campaign_ids=(
            "7001de6c-83f7-4639-9782-23dbda31f5db",
            "858fabe9-b173-4954-9c2e-360a1d170aa9",
        ),
    ),
)


def format_seconds(
    value: float | int | str | None,
) -> str:
    """Converte segundos para HH:MM:SS."""

    if value is None:
        return "—"

    try:
        total_seconds = max(
            0,
            round(float(value)),
        )
    except (TypeError, ValueError):
        return "—"

    hours, remainder = divmod(
        total_seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


def safe_int(value: Any) -> int:
    """Converte um valor para inteiro."""

    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def start_of_day_iso(
    reference_date: date,
) -> str:
    """Início do dia no horário de Brasília."""

    local_datetime = datetime.combine(
        reference_date,
        time.min,
        tzinfo=BRASILIA_TZ,
    )

    return local_datetime.isoformat()


def parse_api_datetime(
    value: Any,
) -> datetime | None:
    """Converte uma data retornada pela API."""

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=BRASILIA_TZ,
            )

        return parsed

    except (TypeError, ValueError):
        return None


def queue_label(
    campaign_name: str,
) -> str:
    """Identifica a fila pelo nome da campanha."""

    normalized = campaign_name.lower()

    if (
        "ligação nova" in normalized
        or "ligacao nova" in normalized
        or "troca de titularidade" in normalized
    ):
        return "Ligação Nova e Troca"

    return "Principal"


ENTRY_DATETIME_FIELDS = (
    "created_at",
    "started_at",
    "start_at",
    "start_date",
    "opened_at",
    "ticket_created_at",
    "inicio",
)

EXIT_DATETIME_FIELDS = (
    "closed_at",
    "ended_at",
    "end_at",
    "end_date",
    "finished_at",
    "ticket_closed_at",
    "fim",
)

WAIT_DURATION_FIELDS = (
    "contact_wait_time",
    "waiting_time",
    "wait_time",
    "customer_wait_time",
    "queue_wait_time",
    "time_waiting",
    "waiting_time_seconds",
    "avg_wait_time_in_seconds",
    "tempo_espera_cliente",
)

HUMAN_DURATION_FIELDS = (
    "total_agent_time",
    "human_service_time",
    "human_service_time_seconds",
    "service_time",
    "attendance_time",
    "handling_time",
    "talk_time",
    "conversation_time",
    "tah",
    "tempo_atendimento_humano",
)


def _first_record_value(record: dict[str, Any], fields: tuple[str, ...]) -> Any:
    """Localiza o primeiro campo conhecido, inclusive em objetos aninhados."""

    for field in fields:
        value = record.get(field)
        if value not in (None, ""):
            return value

    pending = [value for value in record.values() if isinstance(value, dict)]
    visited: set[int] = set()
    while pending:
        current = pending.pop(0)
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        for field in fields:
            value = current.get(field)
            if value not in (None, ""):
                return value
        pending.extend(value for value in current.values() if isinstance(value, dict))
    return None


def parse_duration_seconds(value: Any) -> float | None:
    """Converte durações numéricas, HH:MM:SS ou ISO-8601 para segundos."""

    if value in (None, ""):
        return None
    if isinstance(value, dict):
        nested_value = _first_record_value(
            value,
            ("seconds", "total_seconds", "duration", "value"),
        )
        return parse_duration_seconds(nested_value)
    if isinstance(value, (int, float)):
        return max(0.0, float(value))

    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text.replace(",", ".")))
    except ValueError:
        pass

    day_match = re.fullmatch(
        r"(?:(\d+)\s+days?,\s*)?(\d{1,3}):([0-5]\d):([0-5]\d(?:[.,]\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if day_match:
        days = int(day_match.group(1) or 0)
        hours = int(day_match.group(2))
        minutes = int(day_match.group(3))
        seconds = float(day_match.group(4).replace(",", "."))
        return max(0.0, days * 86400 + hours * 3600 + minutes * 60 + seconds)

    iso_match = re.fullmatch(
        r"P(?:(\d+(?:\.\d+)?)D)?T"
        r"(?:(\d+(?:\.\d+)?)H)?"
        r"(?:(\d+(?:\.\d+)?)M)?"
        r"(?:(\d+(?:\.\d+)?)S)?",
        text,
        flags=re.IGNORECASE,
    )
    if iso_match:
        days, hours, minutes, seconds = (
            float(part or 0) for part in iso_match.groups()
        )
        return max(0.0, days * 86400 + hours * 3600 + minutes * 60 + seconds)
    return None


def _analytic_ticket_id(record: dict[str, Any], position: int) -> str:
    return str(
        record.get("ticket_id")
        or record.get("protocol")
        or record.get("id")
        or record.get("uuid")
        or f"linha-{position}"
    )


def _analytic_queue(
    record: dict[str, Any],
    campaign_queue_map: dict[str, str],
) -> str | None:
    campaign = record.get("campaign")
    campaign_id = str(
        record.get("campaign_id")
        or record.get("campaign__id")
        or (campaign.get("id") if isinstance(campaign, dict) else "")
        or ""
    ).strip()
    if campaign_id in campaign_queue_map:
        return campaign_queue_map[campaign_id]

    campaign_name = str(
        record.get("campaign_name")
        or record.get("campaign__name")
        or (campaign.get("name") if isinstance(campaign, dict) else "")
        or ""
    ).strip()
    return queue_label(campaign_name) if campaign_name else None


def build_hourly_queue_flow(
    records: list[dict[str, Any]],
    reference_date: date,
    campaign_queue_map: dict[str, str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Calcula entrada, saída, resíduo e tempos horários por fila.

    Entradas usam o horário de criação/início do ticket. Saídas e tempos usam
    o mesmo conjunto humano considerado na produtividade, agrupado pelo horário
    de encerramento. O resíduo inicia zerado à meia-noite e nunca fica negativo.
    """

    queue_names = tuple(dict.fromkeys(campaign_queue_map.values()))
    buckets: dict[str, dict[int, dict[str, Any]]] = {
        queue_name: {
            hour: {
                "entries": 0,
                "exits": 0,
                "human_durations": [],
                "human_durations_by_agent": {},
                "wait_durations": [],
            }
            for hour in range(24)
        }
        for queue_name in queue_names
    }
    audit: dict[str, Any] = {
        "records_received": len(records),
        "records_without_queue": 0,
        "entries_considered": 0,
        "entries_without_valid_datetime": 0,
        "exits_considered": 0,
        "exits_without_human_duration": 0,
        "exits_without_wait_duration": 0,
    }
    entry_tickets: set[str] = set()
    exit_tickets: set[str] = set()

    for position, record in enumerate(records):
        queue_name = _analytic_queue(record, campaign_queue_map)
        if queue_name not in buckets:
            audit["records_without_queue"] += 1
            continue

        ticket_id = _analytic_ticket_id(record, position)
        entry_at = parse_api_datetime(_first_record_value(record, ENTRY_DATETIME_FIELDS))
        entry_local: datetime | None = None
        if entry_at is None:
            audit["entries_without_valid_datetime"] += 1
        elif ticket_id not in entry_tickets:
            entry_local = entry_at.astimezone(BRASILIA_TZ)
            if entry_local.date() == reference_date:
                buckets[queue_name][entry_local.hour]["entries"] += 1
                audit["entries_considered"] += 1
                entry_tickets.add(ticket_id)

        username = str(
            record.get("assigned_to_username")
            or record.get("agent_username")
            or ""
        ).strip()
        if not username or username.isdigit() or "external" in username.lower():
            continue

        if entry_local is None:
            entry_local = entry_at.astimezone(BRASILIA_TZ) if entry_at else None
        if entry_local is None or entry_local.date() != reference_date:
            continue

        exit_at = parse_api_datetime(_first_record_value(record, EXIT_DATETIME_FIELDS))
        if exit_at is None or ticket_id in exit_tickets:
            continue
        exit_local = exit_at.astimezone(BRASILIA_TZ)
        if exit_local.date() != reference_date:
            continue

        bucket = buckets[queue_name][exit_local.hour]
        bucket["exits"] += 1
        exit_tickets.add(ticket_id)
        audit["exits_considered"] += 1

        human_duration = parse_duration_seconds(
            _first_record_value(record, HUMAN_DURATION_FIELDS)
        )
        if human_duration is None:
            audit["exits_without_human_duration"] += 1
        else:
            bucket["human_durations"].append(human_duration)
            bucket["human_durations_by_agent"].setdefault(
                username,
                [],
            ).append(human_duration)

        wait_duration = parse_duration_seconds(
            _first_record_value(record, WAIT_DURATION_FIELDS)
        )
        if wait_duration is None:
            audit["exits_without_wait_duration"] += 1
        else:
            bucket["wait_durations"].append(wait_duration)

    result: dict[str, list[dict[str, Any]]] = {}
    for queue_name, hourly_buckets in buckets.items():
        previous_residue = 0
        queue_rows: list[dict[str, Any]] = []
        for hour in range(24):
            bucket = hourly_buckets[hour]
            entries = int(bucket["entries"])
            exits = int(bucket["exits"])
            accumulated_demand = previous_residue + entries
            residue = max(0, accumulated_demand - exits)
            human_values = list(bucket["human_durations"])
            human_values_by_agent = dict(
                bucket["human_durations_by_agent"]
            )
            wait_values = list(bucket["wait_durations"])
            agent_tma_values = [
                sum(agent_values) / len(agent_values)
                for agent_values in human_values_by_agent.values()
                if agent_values
            ]
            queue_rows.append(
                {
                    "hour": hour,
                    "entries": entries,
                    "exits": exits,
                    "accumulated_demand": accumulated_demand,
                    "residue": residue,
                    "tma_seconds": (
                        sum(human_values) / len(human_values)
                        if human_values
                        else None
                    ),
                    "tme_seconds": (
                        sum(wait_values) / len(wait_values)
                        if wait_values
                        else None
                    ),
                    "tamax_seconds": (
                        max(agent_tma_values)
                        if agent_tma_values
                        else None
                    ),
                    "temax_seconds": max(wait_values) if wait_values else None,
                }
            )
            previous_residue = residue
        result[queue_name] = queue_rows

    audit["available_entry_fields"] = sorted(
        field for field in ENTRY_DATETIME_FIELDS if any(field in record for record in records)
    )
    audit["available_human_duration_fields"] = sorted(
        field for field in HUMAN_DURATION_FIELDS if any(field in record for record in records)
    )
    audit["available_wait_duration_fields"] = sorted(
        field for field in WAIT_DURATION_FIELDS if any(field in record for record in records)
    )
    return result, audit


def calculate_agent_tma(
    records: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, float]:
    """Calcula o TMA diário de cada colaborador pelos tickets humanos.

    O resultado é consolidado por login e pode receber registros de várias
    distribuidoras e filas. Tickets repetidos, bots e atendimentos que não
    terminaram na data selecionada são desconsiderados. A data de início não
    restringe o TMA individual.
    """

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    processed_tickets: set[str] = set()

    for position, record in enumerate(records):
        username = str(
            record.get("assigned_to_username")
            or record.get("agent_username")
            or ""
        ).strip()
        if not username or username.isdigit() or "external" in username.lower():
            continue

        closed_at = parse_api_datetime(
            _first_record_value(record, EXIT_DATETIME_FIELDS)
        )
        if closed_at is None:
            continue
        if closed_at.astimezone(BRASILIA_TZ).date() != reference_date:
            continue

        ticket_id = _analytic_ticket_id(record, position)
        if ticket_id in processed_tickets:
            continue

        human_duration = parse_duration_seconds(
            _first_record_value(record, HUMAN_DURATION_FIELDS)
        )
        if human_duration is None:
            continue

        processed_tickets.add(ticket_id)
        login_key = username.casefold()
        totals[login_key] = totals.get(login_key, 0.0) + human_duration
        counts[login_key] = counts.get(login_key, 0) + 1

    return {
        login_key: totals[login_key] / counts[login_key]
        for login_key in totals
        if counts.get(login_key, 0)
    }


def count_previous_day_closed(
    records: list[dict[str, Any]],
    reference_date: date,
) -> int:
    """Conta tickets humanos iniciados ontem e encerrados na data escolhida."""

    previous_date = reference_date - timedelta(days=1)
    processed_tickets: set[str] = set()

    for position, record in enumerate(records):
        username = str(
            record.get("assigned_to_username")
            or record.get("agent_username")
            or ""
        ).strip()
        if not username or username.isdigit() or "external" in username.lower():
            continue

        created_at = parse_api_datetime(
            _first_record_value(record, ENTRY_DATETIME_FIELDS)
        )
        closed_at = parse_api_datetime(
            _first_record_value(record, EXIT_DATETIME_FIELDS)
        )
        if created_at is None or closed_at is None:
            continue
        if created_at.astimezone(BRASILIA_TZ).date() != previous_date:
            continue
        if closed_at.astimezone(BRASILIA_TZ).date() != reference_date:
            continue

        processed_tickets.add(_analytic_ticket_id(record, position))

    return len(processed_tickets)


class MutantClient:
    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        timeout: int = 20,
    ) -> None:
        if not username.strip() or not password:
            raise ValueError(
                "Usuário e senha são obrigatórios."
            )

        self.username = username.strip()
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._agent_id_candidates: list[str] = []
        self._supervisor_agent_id: str | None = None

        self.session = requests.Session()

        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
            max_retries=1,
        )

        self.session.mount(
            "https://",
            adapter,
        )

        self.session.mount(
            "http://",
            adapter,
        )

        self.session.headers.update(
            {
                "Accept": (
                    "application/json, "
                    "text/plain, */*"
                ),
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0.0.0 "
                    "Safari/537.36"
                ),
            }
        )

    def authenticate(self) -> None:
        """Autentica e mantém o token em memória."""

        try:
            response = self.session.post(
                f"{self.base_url}/api/token/",
                json={
                    "username": self.username,
                    "password": self.password,
                },
                headers={
                    "Content-Type": (
                        "application/json"
                    ),
                    "Origin": self.base_url,
                    "Referer": self.base_url,
                },
                timeout=self.timeout,
            )

        except requests.RequestException as exc:
            raise MutantApiError(
                "Não foi possível acessar "
                f"a autenticação: {exc}"
            ) from exc

        data = self._decode_response(
            response,
            "autenticação",
        )

        token = (
            data.get("access")
            if isinstance(data, dict)
            else None
        )

        if not token:
            raise MutantApiError(
                "A autenticação não retornou "
                "o token esperado."
            )

        self.session.headers[
            "Authorization"
        ] = f"Bearer {token}"

        self._agent_id_candidates = _uuid_candidates(
            data,
            _decode_jwt_payload(token),
        )
        # O identificador validado pertence ao token anterior. Após uma nova
        # autenticação ele deve ser conferido novamente pela API.
        self._supervisor_agent_id = None

    def _decode_response(
        self,
        response: requests.Response,
        operation: str,
    ) -> Any:
        """Valida e converte uma resposta em JSON."""

        if not response.ok:
            detail = ""

            try:
                body = response.json()

                if isinstance(body, dict):
                    detail = str(
                        body.get("detail")
                        or body.get("message")
                        or body.get("error")
                        or ""
                    )

            except ValueError:
                pass

            message = (
                f"Falha na {operation}: "
                f"HTTP {response.status_code}."
            )

            if detail:
                message += (
                    f" Detalhe: {detail[:250]}"
                )

            raise MutantApiError(message)

        try:
            return response.json()

        except ValueError as exc:
            raise MutantApiError(
                f"A {operation} não retornou "
                "um JSON válido."
            ) from exc

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        operation: str,
    ) -> Any:
        """Executa uma requisição POST."""

        try:
            response = self.session.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )

        except requests.RequestException as exc:
            raise MutantApiError(
                "Não foi possível concluir "
                f"a {operation}: {exc}"
            ) from exc

        return self._decode_response(
            response,
            operation,
        )

    def _get(
        self,
        path: str,
        params: list[tuple[str, str]],
        operation: str,
    ) -> Any:
        """Executa uma requisição GET."""

        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=self.timeout,
            )

        except requests.RequestException as exc:
            raise MutantApiError(
                "Não foi possível concluir "
                f"a {operation}: {exc}"
            ) from exc

        return self._decode_response(
            response,
            operation,
        )

    def login_logout_report(
        self,
        reference_date: date,
        campaign_id: str = "",
    ) -> bytes:
        """Baixa o relatório Login / Logout diretamente em XLSX.

        A requisição replica a exportação realizada pelo Painel de Controle
        da Mutant. O conteúdo permanece somente em memória.
        """

        params = [
            ("timezone", "America/Sao_Paulo"),
            ("limit", "all"),
            ("offset", "0"),
            ("agent_id", ""),
            (
                "from_date",
                f"{reference_date.isoformat()}T00:00",
            ),
            (
                "to_date",
                f"{reference_date.isoformat()}T23:59",
            ),
            ("campaign_id", campaign_id),
            ("export_type", "xlsx"),
        ]

        try:
            response = self.session.get(
                f"{self.base_url}/api/export/log_report_login_logout",
                params=params,
                headers={
                    "Accept": (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet, application/octet-stream, */*"
                    ),
                    "Referer": self.base_url,
                },
                timeout=max(self.timeout, 60),
            )
        except requests.RequestException as exc:
            raise MutantApiError(
                "Não foi possível baixar o relatório Login / Logout: "
                f"{exc}"
            ) from exc

        if not response.ok:
            # Reutiliza o tratamento seguro de detalhes HTTP.
            self._decode_response(
                response,
                "exportação do relatório Login / Logout",
            )

        content = response.content
        if not content or not content.startswith(b"PK"):
            raise MutantApiError(
                "A exportação do relatório Login / Logout não retornou "
                "uma planilha XLSX válida."
            )

        return content

    def supervisor_agents(self) -> list[dict[str, Any]]:
        """Consulta todos os atendentes visíveis no Painel de Controle.

        O endpoint é paginado e exige o identificador do agente supervisor.
        O identificador é obtido dos metadados retornados na autenticação e
        validado na primeira página antes de ser reutilizado.
        """

        def ordered_candidates() -> list[str]:
            candidates = list(self._agent_id_candidates)
            if self._supervisor_agent_id:
                candidates = [
                    self._supervisor_agent_id,
                    *(
                        candidate
                        for candidate in candidates
                        if candidate != self._supervisor_agent_id
                    ),
                ]
            return candidates

        if not ordered_candidates():
            raise MutantApiError(
                "A autenticação não informou o identificador necessário "
                "para consultar as pausas."
            )

        page_size = 100

        def request_page(
            supervisor_id: str,
            offset: int,
        ) -> tuple[dict[str, Any] | None, str | None]:
            try:
                response = self.session.post(
                    (
                        f"{self.base_url}/api/supervisor/"
                        f"{supervisor_id}/agents"
                    ),
                    params={
                        "id": supervisor_id,
                        "limit": str(page_size),
                        "offset": str(offset),
                        "status": "",
                        "search": "",
                        "ordering": "-status",
                        "is_bot": "false",
                    },
                    json={"campaigns": []},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise MutantApiError(
                    "Não foi possível consultar o monitoramento de pausas: "
                    f"{exc}"
                ) from exc

            if not response.ok:
                return None, f"HTTP {response.status_code}"

            try:
                body = response.json()
            except ValueError:
                return None, "resposta sem JSON válido"

            if not isinstance(body, dict) or not isinstance(
                body.get("results"),
                list,
            ):
                return None, "formato de resposta inesperado"

            return body, None

        first_body: dict[str, Any] | None = None
        selected_id: str | None = None
        candidate_errors: list[str] = []

        # Tokens de acesso da Mutant podem expirar enquanto o fragmento de
        # pausas permanece aberto. Se todos os identificadores retornarem 401,
        # renova o token e repete a tentativa somente uma vez.
        for authentication_attempt in range(2):
            candidate_errors = []
            for candidate in ordered_candidates():
                body, error = request_page(candidate, 0)
                if body is not None:
                    first_body = body
                    selected_id = candidate
                    break
                candidate_errors.append(error or "falha não identificada")

            if first_body is not None:
                break

            only_unauthorized = bool(candidate_errors) and all(
                error == "HTTP 401" for error in candidate_errors
            )
            if authentication_attempt == 0 and only_unauthorized:
                self.authenticate()
                continue
            break

        if first_body is None or selected_id is None:
            error_summary = ", ".join(dict.fromkeys(candidate_errors))
            raise MutantApiError(
                "A Mutant não aceitou o identificador do supervisor para "
                "consultar as pausas"
                + (f" ({error_summary})." if error_summary else ".")
            )

        self._supervisor_agent_id = selected_id
        records: list[dict[str, Any]] = []
        body = first_body
        offset = 0

        for _ in range(100):
            page = body.get("results", [])
            records.extend(
                item for item in page if isinstance(item, dict)
            )

            total = safe_int(body.get("count"))
            offset += len(page)

            if not page:
                break
            if total and offset >= total:
                break
            if not body.get("next") and len(page) < page_size:
                break

            body, error = request_page(selected_id, offset)
            if body is None:
                raise MutantApiError(
                    "A paginação do monitoramento de pausas falhou"
                    + (f" ({error})." if error else ".")
                )

        unique_records: dict[str, dict[str, Any]] = {}
        for position, record in enumerate(records):
            record_id = str(record.get("id") or f"linha-{position}")
            unique_records[record_id] = record

        return list(unique_records.values())

    def ticket_stats(
        self,
        campaign_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Consulta a volumetria dos tickets."""

        body = self._post(
            path="/api/tickets/stats",
            payload={
                "campaign": list(
                    campaign_ids
                ),
            },
            operation=(
                "consulta de estatísticas "
                "dos tickets"
            ),
        )

        if not isinstance(body, dict):
            raise MutantApiError(
                "As estatísticas dos tickets "
                "vieram em formato inesperado."
            )

        return body

    def human_service_time(
        self,
        campaign_ids: tuple[str, ...],
        reference_date: date,
    ) -> dict[str, Any]:
        """Consulta o TMA humano."""

        body = self._post(
            path=(
                "/api/dashboard/"
                "human_service_time"
            ),
            payload={
                "start_date": (
                    start_of_day_iso(
                        reference_date
                    )
                ),
                "campaigns": list(
                    campaign_ids
                ),
            },
            operation=(
                "consulta do TMA humano"
            ),
        )

        if not isinstance(body, dict):
            raise MutantApiError(
                "O TMA humano veio "
                "em formato inesperado."
            )

        return body

    def average_wait_time(
        self,
        campaign_ids: tuple[str, ...],
        reference_date: date,
    ) -> dict[str, Any]:
        """Consulta o TME das campanhas informadas.

        O endpoint retorna ``avg_wait_time`` em segundos e a quantidade de
        tickets usada no cálculo em ``total_tickets``.
        """

        body = self._post(
            path="/api/dashboard/avg_wait_time",
            payload={
                "campaign_ids": list(campaign_ids),
                "created_at": start_of_day_iso(reference_date),
            },
            operation="consulta do TME",
        )

        if not isinstance(body, dict):
            raise MutantApiError(
                "O TME veio em formato inesperado."
            )

        total_tickets = safe_int(body.get("total_tickets"))
        raw_wait_time = body.get("avg_wait_time")

        if raw_wait_time in (None, "") and total_tickets == 0:
            wait_seconds = 0.0
        else:
            try:
                wait_seconds = max(0.0, float(raw_wait_time))
            except (TypeError, ValueError) as exc:
                raise MutantApiError(
                    "A consulta do TME não retornou um tempo válido."
                ) from exc

        return {
            "avg_wait_time": wait_seconds,
            "total_tickets": total_tickets,
        }

    def analytic_report(
        self,
        campaign_ids: tuple[str, ...],
        reference_date: date,
    ) -> list[dict[str, Any]]:
        """Consulta o relatório analítico."""

        page_size = 100
        offset = 0

        records: list[
            dict[str, Any]
        ] = []

        report_start_date = reference_date - timedelta(days=1)
        start_date = (
            f"{report_start_date.isoformat()}"
            "T00:00"
        )

        end_date = (
            f"{reference_date.isoformat()}"
            "T23:59"
        )

        for _ in range(100):
            params: list[
                tuple[str, str]
            ] = [
                (
                    "limit",
                    str(page_size),
                ),
                (
                    "offset",
                    str(offset),
                ),
                (
                    "start_date",
                    start_date,
                ),
                (
                    "end_date",
                    end_date,
                ),
                (
                    "contact_identifier",
                    "",
                ),
                (
                    "protocol",
                    "",
                ),
                (
                    "order_by",
                    "",
                ),
                (
                    "search",
                    "",
                ),
            ]

            for campaign_id in campaign_ids:
                params.append(
                    (
                        "campaign_ids",
                        campaign_id,
                    )
                )

            body = self._get(
                path="/api/reports/analytic",
                params=params,
                operation=(
                    "consulta do relatório "
                    "analítico"
                ),
            )

            if not isinstance(body, dict):
                raise MutantApiError(
                    "O relatório analítico "
                    "retornou um formato "
                    "inesperado."
                )

            page = body.get(
                "results",
                [],
            )

            if not isinstance(page, list):
                raise MutantApiError(
                    "O relatório analítico "
                    "não retornou uma lista."
                )

            records.extend(
                record
                for record in page
                if isinstance(
                    record,
                    dict,
                )
            )

            total = safe_int(
                body.get("count")
            )

            if not page:
                break

            offset += len(page)

            if total and offset >= total:
                break

            if len(page) < page_size:
                break

        return records


def summarize_analytic(
    records: list[dict[str, Any]],
    reference_date: date,
    require_created_on_reference_date: bool = True,
) -> list[dict[str, Any]]:
    """
    Consolida produtividade por login e fila.

    Por padrão, considera somente registros iniciados e encerrados na data
    selecionada. Quando ``require_created_on_reference_date`` é falso, considera
    todos os registros encerrados na data, independentemente do início.
    """

    grouped: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    processed_tickets: set[str] = set()

    for position, record in enumerate(
        records
    ):
        username = str(
            record.get(
                "assigned_to_username"
            )
            or record.get(
                "agent_username"
            )
            or ""
        ).strip()

        name = str(
            record.get(
                "assigned_to_name"
            )
            or record.get(
                "agent_name"
            )
            or username
            or "—"
        ).strip()

        if not username:
            continue

        if username.isdigit():
            continue

        if "external" in username.lower():
            continue

        if require_created_on_reference_date:
            created_at = parse_api_datetime(
                _first_record_value(record, ENTRY_DATETIME_FIELDS)
            )
            if not created_at:
                continue
            if created_at.astimezone(BRASILIA_TZ).date() != reference_date:
                continue

        closed_at = parse_api_datetime(
            record.get("closed_at")
        )

        if not closed_at:
            continue

        closed_local = closed_at.astimezone(
            BRASILIA_TZ
        )

        if (
            closed_local.date()
            != reference_date
        ):
            continue

        ticket_id = str(
            record.get("ticket_id")
            or record.get("protocol")
            or record.get("id")
            or record.get("uuid")
            or f"linha-{position}"
        )

        if ticket_id in processed_tickets:
            continue

        processed_tickets.add(
            ticket_id
        )

        campaign_name = str(
            record.get("campaign_name")
            or "Campanha não informada"
        )

        fila = queue_label(
            campaign_name
        )

        key = (
            username,
            fila,
        )

        if key not in grouped:
            grouped[key] = {
                "Login": username,
                "Nome": name,
                "Fila": fila,
                "Encerrados": 0,
            }

        grouped[key][
            "Encerrados"
        ] += 1

    return sorted(
        grouped.values(),
        key=lambda item: item[
            "Encerrados"
        ],
        reverse=True,
    )
