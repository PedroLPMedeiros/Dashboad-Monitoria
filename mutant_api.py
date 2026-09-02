###################################################################
"""Cliente local para integração com o Mutant360."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter


BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


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
        base_url=(
            "https://neoenergiabrasiliaelektro.mutant360.com.br"
        ),
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

        start_date = (
            f"{reference_date.isoformat()}"
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
) -> list[dict[str, Any]]:
    """
    Consolida produtividade por login e fila.

    Considera somente registros encerrados
    na data selecionada.
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
