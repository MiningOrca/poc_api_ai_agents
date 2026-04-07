from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator


TWO_PLACES = Decimal("0.01")
SUPPORTED_CURRENCY = "EUR"
MAX_DAILY_TRANSFER_COUNT = 5
MAX_DAILY_TRANSFER_AMOUNT = Decimal("5000.00")


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    @field_serializer("*", when_used="json")
    def _serialize_common_values(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value


class ApiError(ApiModel):
    error: str = Field(..., examples=["invalid request"])
    details: list[dict[str, Any]] | None = Field(
        default=None,
        examples=[[{"field": "amount", "message": "Amount must be greater than 0"}]],
    )


class CreateUserRequest(ApiModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Alice"])
    email: EmailStr = Field(..., examples=["alice@example.com"])

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name must not be blank")
        return cleaned


class CreateUserResponse(ApiModel):
    userId: str = Field(..., examples=["u-1004"])
    name: str = Field(..., examples=["Dave"])
    email: EmailStr = Field(..., examples=["dave@example.com"])


class DepositRequest(ApiModel):
    userId: str = Field(..., examples=["u-1001"])
    amount: Decimal = Field(..., examples=[100.50])
    currency: Literal["EUR"] = Field(..., examples=["EUR"])

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        return normalize_positive_amount(value)


class DepositResponse(ApiModel):
    userId: str = Field(..., examples=["u-1001"])
    newBalance: Decimal = Field(..., examples=[200.50])
    currency: Literal["EUR"] = Field(..., examples=["EUR"])


class TransferRequest(ApiModel):
    senderId: str = Field(..., examples=["u-1001"])
    receiverId: str = Field(..., examples=["u-1002"])
    amount: Decimal = Field(..., examples=[30.00])
    currency: Literal["EUR"] = Field(..., examples=["EUR"])
    comment: str | None = Field(default=None, max_length=255, examples=["Dinner"])

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        return normalize_positive_amount(value)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TransferResponse(ApiModel):
    operationId: str = Field(..., examples=["tr-9001"])
    status: Literal["SUCCESS"] = Field(..., examples=["SUCCESS"])
    senderId: str = Field(..., examples=["u-1001"])
    receiverId: str = Field(..., examples=["u-1002"])
    amount: Decimal = Field(..., examples=[30.00])
    currency: Literal["EUR"] = Field(..., examples=["EUR"])


class TransactionItem(ApiModel):
    operationId: str = Field(..., examples=["tr-9001"])
    type: Literal["DEPOSIT", "OUTGOING", "INCOMING"] = Field(..., examples=["OUTGOING"])
    amount: Decimal = Field(..., examples=[30.00])
    currency: Literal["EUR"] = Field(..., examples=["EUR"])
    timestamp: datetime = Field(..., examples=["2026-03-24T10:15:00Z"])
    counterpartyId: str | None = Field(default=None, examples=["u-1002"])
    comment: str | None = Field(default=None, examples=["Dinner"])


class TransactionsResponse(ApiModel):
    userId: str = Field(..., examples=["u-1001"])
    transactions: list[TransactionItem]


class ResetResponse(ApiModel):
    status: Literal["RESET"] = "RESET"


class SetNowRequest(ApiModel):
    now: datetime = Field(..., examples=["2026-03-24T10:15:00Z"])


class SetNowResponse(ApiModel):
    status: Literal["NOW_SET"] = "NOW_SET"
    now: datetime


class StateSnapshot(ApiModel):
    users: dict[str, dict[str, Any]]
    balances: dict[str, Decimal]
    transactions: dict[str, list[TransactionItem]]
    serverNow: datetime


def normalize_positive_amount(value: Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Amount must be a valid decimal number") from exc

    if normalized <= 0:
        raise ValueError("Amount must be greater than 0")
    if normalized != normalized.quantize(TWO_PLACES):
        raise ValueError("Amount must have at most two decimal places")
    return normalized.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class MockState:
    def __init__(self) -> None:
        self._seed_now = datetime(2026, 3, 24, 10, 0, 0, tzinfo=timezone.utc)
        self.reset()

    def reset(self) -> None:
        self.server_now = self._seed_now
        self.user_sequence = 1004
        self.transfer_sequence = 9001
        self.deposit_sequence = 7001

        self.users: dict[str, dict[str, str]] = {
            "u-1001": {"userId": "u-1001", "name": "Alice", "email": "alice@example.com"},
            "u-1002": {"userId": "u-1002", "name": "Bob", "email": "bob@example.com"},
            "u-1003": {"userId": "u-1003", "name": "Carol", "email": "carol@example.com"},
        }
        self.balances: dict[str, Decimal] = {
            "u-1001": Decimal("100.00"),
            "u-1002": Decimal("20.00"),
            "u-1003": Decimal("0.00"),
        }
        self.transactions: dict[str, list[TransactionItem]] = {
            "u-1001": [],
            "u-1002": [],
            "u-1003": [],
        }
        self.daily_outgoing_count: dict[tuple[str, str], int] = defaultdict(int)
        self.daily_outgoing_amount: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0.00"))

    def set_now(self, new_now: datetime) -> None:
        self.server_now = new_now.astimezone(timezone.utc)

    def _tick(self) -> datetime:
        current = self.server_now
        self.server_now = self.server_now + timedelta(seconds=1)
        return current

    def _current_day_key(self) -> str:
        return self.server_now.astimezone(timezone.utc).date().isoformat()

    def create_user(self, name: str, email: str) -> dict[str, str]:
        normalized_email = email.strip().lower()
        for existing in self.users.values():
            if existing["email"].lower() == normalized_email:
                raise conflict("Email already exists")

        user_id = f"u-{self.user_sequence}"
        self.user_sequence += 1

        user = {
            "userId": user_id,
            "name": name.strip(),
            "email": normalized_email,
        }
        self.users[user_id] = user
        self.balances[user_id] = Decimal("0.00")
        self.transactions[user_id] = []
        return user

    def deposit(self, user_id: str, amount: Decimal) -> DepositResponse:
        self._ensure_user_exists(user_id)
        self.balances[user_id] = (self.balances[user_id] + amount).quantize(TWO_PLACES)

        operation_id = f"dep-{self.deposit_sequence}"
        self.deposit_sequence += 1

        timestamp = self._tick()
        self.transactions[user_id].insert(
            0,
            TransactionItem(
                operationId=operation_id,
                type="DEPOSIT",
                amount=amount,
                currency=SUPPORTED_CURRENCY,
                timestamp=timestamp,
                counterpartyId=None,
                comment=None,
            ),
        )

        return DepositResponse(
            userId=user_id,
            newBalance=self.balances[user_id],
            currency=SUPPORTED_CURRENCY,
        )

    def transfer(
        self,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        comment: str | None,
    ) -> TransferResponse:
        self._ensure_user_exists(sender_id, role="sender")
        self._ensure_user_exists(receiver_id, role="receiver")

        if sender_id == receiver_id:
            raise bad_request("senderId and receiverId must be different")

        day_key = self._current_day_key()
        quota_key = (sender_id, day_key)

        if self.daily_outgoing_count[quota_key] >= MAX_DAILY_TRANSFER_COUNT:
            raise forbidden("Daily limit on number of outgoing transfers exceeded")

        next_daily_amount = (self.daily_outgoing_amount[quota_key] + amount).quantize(TWO_PLACES)
        if next_daily_amount > MAX_DAILY_TRANSFER_AMOUNT:
            raise too_many_requests("Daily amount limit exceeded")

        if self.balances[sender_id] < amount:
            raise payment_required("Insufficient funds")

        self.balances[sender_id] = (self.balances[sender_id] - amount).quantize(TWO_PLACES)
        self.balances[receiver_id] = (self.balances[receiver_id] + amount).quantize(TWO_PLACES)

        self.daily_outgoing_count[quota_key] += 1
        self.daily_outgoing_amount[quota_key] = next_daily_amount

        operation_id = f"tr-{self.transfer_sequence}"
        self.transfer_sequence += 1
        timestamp = self._tick()

        outgoing = TransactionItem(
            operationId=operation_id,
            type="OUTGOING",
            amount=amount,
            currency=SUPPORTED_CURRENCY,
            timestamp=timestamp,
            counterpartyId=receiver_id,
            comment=comment,
        )
        incoming = TransactionItem(
            operationId=operation_id,
            type="INCOMING",
            amount=amount,
            currency=SUPPORTED_CURRENCY,
            timestamp=timestamp,
            counterpartyId=sender_id,
            comment=comment,
        )

        self.transactions[sender_id].insert(0, outgoing)
        self.transactions[receiver_id].insert(0, incoming)

        return TransferResponse(
            operationId=operation_id,
            status="SUCCESS",
            senderId=sender_id,
            receiverId=receiver_id,
            amount=amount,
            currency=SUPPORTED_CURRENCY,
        )

    def get_transactions(self, user_id: str, limit: int, offset: int) -> TransactionsResponse:
        self._ensure_user_exists(user_id)
        items = self.transactions[user_id][offset : offset + limit]
        return TransactionsResponse(userId=user_id, transactions=items)

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            users=deepcopy(self.users),
            balances=deepcopy(self.balances),
            transactions=deepcopy(self.transactions),
            serverNow=self.server_now,
        )

    def _ensure_user_exists(self, user_id: str, role: str = "user") -> None:
        if user_id not in self.users:
            raise not_found(f"{role.capitalize()} not found: {user_id}")


def bad_request(message: str, details: list[dict[str, Any]] | None = None) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": message, "details": details})


def payment_required(message: str) -> HTTPException:
    return HTTPException(status_code=402, detail={"error": message})


def forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"error": message})


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": message})


def conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"error": message})


def too_many_requests(message: str) -> HTTPException:
    return HTTPException(status_code=429, detail={"error": message})


state = MockState()

app = FastAPI(
    title="E-Wallet Mock API",
    version="1.0.0",
    description=(
        "Stateful mock API for the QA Automation with AI Agents test assignment. "
        "Implements create user, deposit, transfer, transaction history, and test-control endpoints."
    ),
)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details: list[dict[str, Any]] = []
    for err in exc.errors():
        field = ".".join(str(part) for part in err.get("loc", []) if part != "body")
        details.append(
            {
                "field": field or "request",
                "message": err.get("msg", "Invalid value"),
            }
        )
    return JSONResponse(
        status_code=400,
        content=ApiError(error="Invalid request data", details=details).model_dump(mode="json"),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        payload = ApiError(**detail).model_dump(mode="json")
    else:
        payload = ApiError(error=str(detail)).model_dump(mode="json")
    return JSONResponse(status_code=exc.status_code, content=payload)


common_error_responses = {
    400: {"model": ApiError, "description": "Invalid request"},
    404: {"model": ApiError, "description": "Entity not found"},
    409: {"model": ApiError, "description": "Conflict"},
    402: {"model": ApiError, "description": "Payment required / insufficient funds"},
    403: {"model": ApiError, "description": "Forbidden / limit exceeded"},
    429: {"model": ApiError, "description": "Too many requests / daily amount limit exceeded"},
}


@app.post(
    "/users",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
    summary="Create user",
    responses={
        400: {"model": ApiError, "description": "Invalid user data"},
        409: {"model": ApiError, "description": "Email already exists"},
    },
)
def create_user(request: CreateUserRequest) -> CreateUserResponse:
    user = state.create_user(name=request.name, email=str(request.email))
    return CreateUserResponse(**user)


@app.post(
    "/wallets/deposit",
    response_model=DepositResponse,
    tags=["wallets"],
    summary="Deposit money to wallet",
    responses={
        400: {"model": ApiError, "description": "Invalid deposit request"},
        404: {"model": ApiError, "description": "User not found"},
    },
)
def deposit(request: DepositRequest) -> DepositResponse:
    if request.currency != SUPPORTED_CURRENCY:
        raise bad_request(f"Unsupported currency: {request.currency}")
    return state.deposit(user_id=request.userId, amount=request.amount)


@app.post(
    "/wallets/transfer",
    response_model=TransferResponse,
    tags=["wallets"],
    summary="Transfer money between users",
    responses={
        400: {"model": ApiError, "description": "Invalid transfer request"},
        402: {"model": ApiError, "description": "Insufficient funds"},
        403: {"model": ApiError, "description": "Daily count limit exceeded"},
        404: {"model": ApiError, "description": "Sender or receiver not found"},
        429: {"model": ApiError, "description": "Daily amount limit exceeded"},
    },
)
def transfer(request: TransferRequest) -> TransferResponse:
    if request.currency != SUPPORTED_CURRENCY:
        raise bad_request(f"Unsupported currency: {request.currency}")
    return state.transfer(
        sender_id=request.senderId,
        receiver_id=request.receiverId,
        amount=request.amount,
        comment=request.comment,
    )


@app.get(
    "/wallets/{userId}/transactions",
    response_model=TransactionsResponse,
    tags=["wallets"],
    summary="Get transaction history",
    responses={
        400: {"model": ApiError, "description": "Invalid limit or offset"},
        404: {"model": ApiError, "description": "User not found"},
    },
)
def get_transactions(
    userId: str = Path(..., description="User identifier", examples=["u-1001"]),
    limit: int = Query(20, description="Page size, default 20, maximum 100"),
    offset: int = Query(0, description="Pagination offset, must be >= 0"),
) -> TransactionsResponse:
    if limit < 0:
        raise bad_request("limit must be >= 0")
    if limit > 100:
        raise bad_request("limit must be <= 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    return state.get_transactions(user_id=userId, limit=limit, offset=offset)


@app.post(
    "/__test/reset",
    response_model=ResetResponse,
    tags=["test-control"],
    summary="Reset mock state to initial seed data",
)
def reset_state() -> ResetResponse:
    state.reset()
    return ResetResponse()
#
#
# @app.post(
#     "/__test/set-now",
#     response_model=SetNowResponse,
#     tags=["test-control"],
#     summary="Set server time for reproducible daily-limit tests",
# )
# def set_now(request: SetNowRequest) -> SetNowResponse:
#     state.set_now(request.now)
#     return SetNowResponse(now=state.server_now)
#
#
# @app.get(
#     "/__test/state",
#     response_model=StateSnapshot,
#     tags=["test-control"],
#     summary="Get full internal state snapshot",
# )
# def get_state() -> StateSnapshot:
#     return state.snapshot()
#
#
# @app.get(
#     "/health",
#     tags=["service"],
#     summary="Health check",
# )
# def health() -> dict[str, str]:
#     return {"status": "ok", "now": iso_z(state.server_now)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mock_api:app", host="127.0.0.1", port=8000, reload=True)
