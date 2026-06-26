from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


APP_NAME = "QueueStorm Investigator"

EVIDENCE = {"consistent", "inconsistent", "insufficient_data"}
CASE_TYPES = {
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
}
SEVERITIES = {"low", "medium", "high", "critical"}
DEPARTMENTS = {
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
}

CASE_TO_DEPT = {
    "wrong_transfer": "dispute_resolution",
    "payment_failed": "payments_ops",
    "refund_request": "customer_support",
    "duplicate_payment": "payments_ops",
    "merchant_settlement_delay": "merchant_operations",
    "agent_cash_in_issue": "agent_operations",
    "phishing_or_social_engineering": "fraud_risk",
    "other": "customer_support",
}

BN_DIGITS = {
    ord("\u09e6"): "0", ord("\u09e7"): "1", ord("\u09e8"): "2", ord("\u09e9"): "3", ord("\u09ea"): "4",
    ord("\u09eb"): "5", ord("\u09ec"): "6", ord("\u09ed"): "7", ord("\u09ee"): "8", ord("\u09ef"): "9",
}


class Transaction(BaseModel):
    model_config = ConfigDict(extra="allow")

    transaction_id: Optional[str] = None
    timestamp: Optional[str] = None
    type: Optional[str] = None
    amount: Optional[float] = None
    counterparty: Optional[str] = None
    status: Optional[str] = None


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    ticket_id: str = Field(min_length=1)
    complaint: str = Field(min_length=1)
    language: Optional[str] = None
    channel: Optional[str] = None
    user_type: Optional[str] = None
    campaign_context: Optional[str] = None
    transaction_history: Optional[list[Transaction]] = None
    metadata: Optional[dict[str, Any]] = None


class TicketResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: str
    case_type: str
    severity: str
    department: str
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = None
    reason_codes: Optional[list[str]] = None


app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    default_response_class=JSONResponse,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_request",
            "message": "Required JSON fields are missing or invalid.",
        },
    )


@app.exception_handler(Exception)
async def safe_error_handler(_: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "The service could not analyze this ticket safely.",
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(ticket: TicketRequest):
    ctx = build_context(ticket)
    result = investigate(ticket, ctx)
    return enforce_output_safety(result)


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def norm(value: Any) -> str:
    return safe_text(value).translate(BN_DIGITS).lower()


def has_bangla(text: str) -> bool:
    return any("\u0980" <= ch <= "\u09ff" for ch in text)


def contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def extract_amounts(text: str) -> list[float]:
    t = norm(text)
    amounts: list[float] = []

    currency_pattern = r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:taka|tk|bdt|\u099f\u09be\u0995\u09be)"
    for match in re.findall(currency_pattern, t):
        try:
            amounts.append(float(match.replace(",", "")))
        except ValueError:
            pass

    if amounts:
        return unique_numbers(amounts)

    for match in re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", t):
        raw = match.replace(",", "")
        if len(raw) > 7:
            continue
        try:
            value = float(raw)
            if 1 <= value <= 1_000_000:
                amounts.append(value)
        except ValueError:
            pass

    return unique_numbers(amounts)


def unique_numbers(nums: list[float]) -> list[float]:
    seen = set()
    out = []
    for num in nums:
        key = round(float(num), 2)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def parse_time(timestamp: Optional[str]) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        return None


def detect_language(ticket: TicketRequest) -> str:
    raw = norm(ticket.language)
    if raw in {"en", "bn", "mixed"}:
        return raw
    if has_bangla(ticket.complaint) and re.search(r"[a-zA-Z]", ticket.complaint):
        return "mixed"
    if has_bangla(ticket.complaint):
        return "bn"
    return "en"


def build_context(ticket: TicketRequest) -> dict[str, Any]:
    complaint = safe_text(ticket.complaint)
    history = list(ticket.transaction_history or [])
    return {
        "text": norm(complaint),
        "language": detect_language(ticket),
        "amounts": extract_amounts(complaint),
        "channel": norm(ticket.channel),
        "user_type": norm(ticket.user_type),
        "history": history,
    }


def classify_case(ctx: dict[str, Any]) -> str:
    text = ctx["text"]
    user_type = ctx["user_type"]
    channel = ctx["channel"]
    history: list[Transaction] = ctx["history"]
    bn_like = ctx["language"] == "bn" or has_bangla(text)

    if contains_any(text, [
        "otp", "pin", "password", "passcode", "cvv", "full card",
        "blocked if", "account will be blocked", "verify your account",
        "share code", "secret code", "unlock account",
        "\u0993\u099f\u09bf\u09aa\u09bf", "\u09aa\u09bf\u09a8", "\u09aa\u09be\u09b8\u0993\u09df\u09be\u09b0\u09cd\u09a1",
        "\u09ac\u09cd\u09b2\u0995",
    ]):
        return "phishing_or_social_engineering"

    if contains_any(text, [
        "twice", "double", "duplicate", "deducted twice", "charged twice",
        "\u09a6\u09c1\u0987\u09ac\u09be\u09b0", "\u09a6\u09c1\u09ac\u09be\u09b0", "\u09a1\u09be\u09ac\u09b2",
    ]):
        return "duplicate_payment"

    if contains_any(text, [
        "failed", "failure", "app showed failed", "payment failed",
        "mobile recharge", "recharge", "balance was deducted", "deducted",
        "\u09ab\u09c7\u0987\u09b2", "\u09ac\u09cd\u09af\u09b0\u09cd\u09a5", "\u0995\u09c7\u099f\u09c7", "\u09a1\u09bf\u09a1\u09be\u0995\u09cd\u099f",
    ]):
        return "payment_failed"

    if contains_any(text, [
        "refund", "return my money", "changed my mind", "don't want it",
        "do not want it", "cancel order", "cancelled order",
        "\u09b0\u09bf\u09ab\u09be\u09a8\u09cd\u09a1", "\u09ab\u09c7\u09b0\u09a4",
    ]):
        return "refund_request"

    if user_type == "merchant" or channel == "merchant_portal" or contains_any(text, [
        "settlement", "settled", "sales not settled", "not been settled",
        "sales of", "batch status",
        "\u09b8\u09c7\u099f\u09c7\u09b2\u09ae\u09c7\u09a8\u09cd\u099f", "\u09ae\u09be\u09b0\u09cd\u099a\u09c7\u09a8\u09cd\u099f",
    ]):
        return "merchant_settlement_delay"

    if contains_any(text, [
        "cash in", "cash-in", "cashin", "agent", "not reflected",
        "\u0995\u09cd\u09af\u09be\u09b6 \u0987\u09a8", "\u098f\u099c\u09c7\u09a8\u09cd\u099f",
        "\u09ac\u09cd\u09af\u09be\u09b2\u09c7\u09a8\u09cd\u09b8\u09c7", "\u099f\u09be\u0995\u09be \u0986\u09b8\u09c7\u09a8\u09bf",
    ]):
        return "agent_cash_in_issue"

    if contains_any(text, [
        "wrong number", "wrong person", "wrong recipient", "mistake",
        "typed it wrong", "typed wrong", "sent to wrong", "didn't get it",
        "did not get it", "money back",
        "\u09ad\u09c1\u09b2", "\u09aa\u09be\u09a0\u09bf\u09df\u09c7\u099b\u09bf", "\u09aa\u09be\u09a0\u09bf\u09af\u09bc\u09c7\u099b\u09bf",
        "\u09aa\u09be\u09df\u09a8\u09bf", "\u09aa\u09be\u09af\u09bc\u09a8\u09bf",
    ]):
        return "wrong_transfer"

    if bn_like:
        tx_types = {norm(tx.type) for tx in history}
        statuses = {norm(tx.status) for tx in history}

        if "cash_in" in tx_types:
            return "agent_cash_in_issue"
        if "settlement" in tx_types or user_type == "merchant" or channel == "merchant_portal":
            return "merchant_settlement_delay"
        if "payment" in tx_types and ("failed" in statuses or "pending" in statuses):
            return "payment_failed"
        if "transfer" in tx_types:
            return "wrong_transfer"

    return "other"


def expected_tx_type(case_type: str) -> set[str]:
    mapping = {
        "wrong_transfer": {"transfer"},
        "payment_failed": {"payment"},
        "refund_request": {"payment", "refund"},
        "duplicate_payment": {"payment"},
        "merchant_settlement_delay": {"settlement"},
        "agent_cash_in_issue": {"cash_in"},
    }
    return mapping.get(case_type, set())


def status_score(case_type: str, status: str) -> int:
    if case_type == "payment_failed" and status in {"failed", "pending"}:
        return 25
    if case_type in {"wrong_transfer", "refund_request", "duplicate_payment"} and status == "completed":
        return 15
    if case_type in {"merchant_settlement_delay", "agent_cash_in_issue"} and status == "pending":
        return 25
    return 0


def score_transaction(tx: Transaction, case_type: str, ctx: dict[str, Any]) -> int:
    text = ctx["text"]
    amounts = ctx["amounts"]
    score = 0

    tx_id_text = norm(tx.transaction_id)
    tx_type = norm(tx.type)
    status = norm(tx.status)
    counterparty = norm(tx.counterparty)

    if tx_id_text and tx_id_text in text:
        score += 120

    if tx.amount is not None and amounts:
        for amount in amounts:
            if abs(float(tx.amount) - amount) < 0.01:
                score += 45
                break

    if tx_type in expected_tx_type(case_type):
        score += 35

    score += status_score(case_type, status)

    if counterparty and counterparty in text:
        score += 35

    return score


def find_duplicate_transaction(history: list[Transaction]) -> Optional[Transaction]:
    candidates: list[tuple[float, Transaction]] = []

    for i, first in enumerate(history):
        for second in history[i + 1:]:
            if norm(first.type) != "payment" or norm(second.type) != "payment":
                continue
            if norm(first.status) != "completed" or norm(second.status) != "completed":
                continue
            if first.amount is None or second.amount is None:
                continue
            if abs(float(first.amount) - float(second.amount)) >= 0.01:
                continue
            if norm(first.counterparty) != norm(second.counterparty):
                continue

            t1 = parse_time(first.timestamp)
            t2 = parse_time(second.timestamp)
            gap = 999999.0
            if t1 and t2:
                gap = abs((t2 - t1).total_seconds())

            candidates.append((gap, second))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def find_relevant_transaction(case_type: str, ctx: dict[str, Any]) -> tuple[Optional[Transaction], bool]:
    history: list[Transaction] = ctx["history"]

    if not history or case_type in {"phishing_or_social_engineering", "other"}:
        return None, False

    if case_type == "duplicate_payment":
        duplicate = find_duplicate_transaction(history)
        if duplicate:
            return duplicate, False

    scored = [(score_transaction(tx, case_type, ctx), tx) for tx in history]
    scored = [(score, tx) for score, tx in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return None, False

    best_score, best_tx = scored[0]

    if case_type == "wrong_transfer" and ctx["amounts"]:
        amount_matches = [
            tx for tx in history
            if norm(tx.type) == "transfer"
            and tx.amount is not None
            and any(abs(float(tx.amount) - amount) < 0.01 for amount in ctx["amounts"])
        ]
        if len(amount_matches) > 1 and best_score < 100:
            return None, True

    tied = [tx for score, tx in scored if score == best_score]
    if len(tied) > 1 and best_score < 100:
        return None, True

    return best_tx, False


def wrong_transfer_inconsistent(tx: Optional[Transaction], history: list[Transaction]) -> bool:
    if not tx or not tx.counterparty:
        return False

    same_completed = 0
    for item in history:
        if norm(item.type) == "transfer" and norm(item.status) == "completed" and norm(item.counterparty) == norm(tx.counterparty):
            same_completed += 1

    return same_completed >= 3


def evidence_verdict(case_type: str, tx: Optional[Transaction], ambiguous: bool, ctx: dict[str, Any]) -> str:
    if case_type in {"phishing_or_social_engineering", "other"}:
        return "insufficient_data"

    if ambiguous or not tx:
        return "insufficient_data"

    status = norm(tx.status)

    if case_type == "wrong_transfer":
        return "inconsistent" if wrong_transfer_inconsistent(tx, ctx["history"]) else "consistent"

    if case_type == "payment_failed":
        return "consistent" if status in {"failed", "pending"} else "inconsistent"

    if case_type == "refund_request":
        return "consistent"

    if case_type == "duplicate_payment":
        return "consistent"

    if case_type == "merchant_settlement_delay":
        return "consistent" if status == "pending" else "inconsistent"

    if case_type == "agent_cash_in_issue":
        return "consistent" if status in {"pending", "failed"} else "inconsistent"

    return "insufficient_data"


def tx_id(tx: Optional[Transaction]) -> Optional[str]:
    return tx.transaction_id if tx and tx.transaction_id else None


def amount_value(tx: Optional[Transaction], ctx: dict[str, Any]) -> float:
    if tx and tx.amount is not None:
        return float(tx.amount)
    if ctx["amounts"]:
        return max(ctx["amounts"])
    return 0.0


def format_amount(tx: Optional[Transaction], ctx: dict[str, Any]) -> str:
    amount = amount_value(tx, ctx)
    if amount == 0:
        return "an unspecified amount"
    if float(amount).is_integer():
        return f"{int(amount)} BDT"
    return f"{amount} BDT"


def severity_for(case_type: str, verdict: str, tx: Optional[Transaction], ctx: dict[str, Any]) -> str:
    amount = amount_value(tx, ctx)

    if case_type == "phishing_or_social_engineering":
        return "critical"

    if case_type == "duplicate_payment":
        return "critical" if amount >= 25000 else "high"

    if case_type == "wrong_transfer":
        if verdict == "insufficient_data":
            return "medium"
        if amount >= 25000:
            return "critical"
        if amount >= 1000:
            return "high"
        return "medium"

    if case_type == "payment_failed":
        return "critical" if amount >= 25000 else "high"

    if case_type == "agent_cash_in_issue":
        if amount >= 25000:
            return "critical"
        if amount >= 1000:
            return "high"
        return "medium"

    if case_type == "merchant_settlement_delay":
        return "high" if amount >= 30000 else "medium"

    if case_type == "refund_request":
        return "medium" if amount >= 5000 else "low"

    return "low"


def human_review_needed(case_type: str, verdict: str, severity: str, ambiguous: bool) -> bool:
    if case_type == "phishing_or_social_engineering":
        return True
    if ambiguous:
        return False
    if case_type in {"wrong_transfer", "duplicate_payment", "agent_cash_in_issue"} and verdict != "insufficient_data":
        return True
    if severity == "critical":
        return True
    return False


def make_summary(case_type: str, verdict: str, tx: Optional[Transaction], ambiguous: bool, ctx: dict[str, Any]) -> str:
    tid = tx_id(tx)
    amount = format_amount(tx, ctx)

    if case_type == "wrong_transfer":
        if ambiguous:
            return "Customer reports a transfer issue, but multiple transactions could match the complaint. The correct transaction cannot be identified without more details."
        if verdict == "inconsistent":
            return f"Customer claims {tid or 'a transfer'} was wrong, but transaction history shows repeated completed transfers to the same recipient."
        return f"Customer reports a wrong transfer involving {tid or 'an unidentified transfer'} for {amount}."

    if case_type == "payment_failed":
        return f"Customer reports a failed payment or unexpected balance deduction. Relevant transaction: {tid or 'not identified'}."

    if case_type == "refund_request":
        return f"Customer requests a refund for {tid or 'a transaction'} for {amount}. Refund eligibility depends on merchant or service policy."

    if case_type == "duplicate_payment":
        return f"Customer reports duplicate payment. The suspected duplicate transaction is {tid or 'not identified'}."

    if case_type == "merchant_settlement_delay":
        return f"Merchant reports delayed settlement. Relevant settlement transaction: {tid or 'not identified'}."

    if case_type == "agent_cash_in_issue":
        return f"Customer reports cash-in not reflected in balance. Relevant cash-in transaction: {tid or 'not identified'}."

    if case_type == "phishing_or_social_engineering":
        return "Customer reports a possible phishing or social engineering attempt involving sensitive credential requests."

    return "Customer complaint is vague or outside the main taxonomy; more details may be required."


def next_action(case_type: str, verdict: str, tx: Optional[Transaction], ambiguous: bool) -> str:
    tid = tx_id(tx) or "the relevant transaction"

    if ambiguous:
        return "Ask the customer for the missing identifying detail before selecting a transaction or starting a dispute."

    if case_type == "wrong_transfer":
        if verdict == "inconsistent":
            return f"Flag for human review and verify whether {tid} is genuinely a wrong transfer given the transaction pattern."
        return f"Verify {tid} details and route through the wrong-transfer dispute workflow."

    if case_type == "payment_failed":
        return f"Check ledger and payment gateway status for {tid}. Any eligible amount should be handled through official channels."

    if case_type == "refund_request":
        return "Explain that refund eligibility depends on policy and guide the customer through official support or merchant channels."

    if case_type == "duplicate_payment":
        return f"Verify the suspected duplicate {tid} with payments operations and the biller or merchant."

    if case_type == "merchant_settlement_delay":
        return f"Route to merchant operations to verify settlement batch status for {tid}."

    if case_type == "agent_cash_in_issue":
        return f"Route to agent operations to verify cash-in status for {tid}."

    if case_type == "phishing_or_social_engineering":
        return "Escalate to fraud risk, record the incident, and remind the customer never to share PIN, OTP, or password."

    return "Ask the customer for transaction ID, amount, time, and a clearer description of the issue."


def customer_reply(case_type: str, tx: Optional[Transaction], ambiguous: bool) -> str:
    tid = tx_id(tx) or "the relevant transaction"

    if case_type == "phishing_or_social_engineering":
        return "Thank you for reporting this. We never ask for your PIN, OTP, password, or full card number. Please do not share these with anyone. Our fraud team will review the incident through official channels."

    if ambiguous:
        return "Thank you for reaching out. We found multiple possible transactions, so please share the transaction ID, amount, time, or recipient number to help us identify the correct one. Please do not share your PIN or OTP with anyone."

    if case_type == "wrong_transfer":
        return f"We have noted your concern about transaction {tid}. Please do not share your PIN or OTP with anyone. Our dispute team will review the case and contact you through official support channels."

    if case_type == "payment_failed":
        return f"We have noted that transaction {tid} may have caused an unexpected balance issue. Our payments team will review it and any eligible amount will be returned through official channels. Please do not share your PIN or OTP with anyone."

    if case_type == "refund_request":
        return "Thank you for reaching out. Refund eligibility depends on the applicable merchant or service policy. We can guide you through the official support process. Please do not share your PIN or OTP with anyone."

    if case_type == "duplicate_payment":
        return f"We have noted the possible duplicate payment for transaction {tid}. Our payments team will verify it and any eligible amount will be returned through official channels. Please do not share your PIN or OTP with anyone."

    if case_type == "merchant_settlement_delay":
        return f"We have noted your concern about settlement {tid}. Our merchant operations team will check the batch status and update you through official channels."

    if case_type == "agent_cash_in_issue":
        return f"We have noted your concern about transaction {tid}. Our agent operations team will verify the cash-in status and update you through official channels. Please do not share your PIN or OTP with anyone."

    return "Thank you for reaching out. Please share the transaction ID, amount, time, and a short description of what went wrong so we can help through official support channels. Please do not share your PIN or OTP with anyone."


def confidence_for(case_type: str, verdict: str, tx: Optional[Transaction], ambiguous: bool) -> float:
    if case_type == "phishing_or_social_engineering":
        return 0.95
    if ambiguous:
        return 0.65
    if not tx and verdict == "insufficient_data":
        return 0.60
    if verdict == "consistent":
        return 0.90
    if verdict == "inconsistent":
        return 0.76
    return 0.68


def reason_codes(case_type: str, verdict: str, tx: Optional[Transaction], ambiguous: bool) -> list[str]:
    codes = [case_type]
    if tx:
        codes.append("transaction_match")
    if ambiguous:
        codes.extend(["ambiguous_match", "needs_clarification"])
    if verdict == "inconsistent":
        codes.append("evidence_inconsistent")
    if verdict == "insufficient_data":
        codes.append("insufficient_data")
    if case_type == "phishing_or_social_engineering":
        codes.extend(["credential_protection", "critical_escalation"])
    return list(dict.fromkeys(codes))


def investigate(ticket: TicketRequest, ctx: dict[str, Any]) -> dict[str, Any]:
    case_type = classify_case(ctx)
    relevant_tx, ambiguous = find_relevant_transaction(case_type, ctx)
    verdict = evidence_verdict(case_type, relevant_tx, ambiguous, ctx)
    severity = severity_for(case_type, verdict, relevant_tx, ctx)
    department = CASE_TO_DEPT.get(case_type, "customer_support")

    return {
        "ticket_id": ticket.ticket_id,
        "relevant_transaction_id": tx_id(relevant_tx),
        "evidence_verdict": verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": make_summary(case_type, verdict, relevant_tx, ambiguous, ctx),
        "recommended_next_action": next_action(case_type, verdict, relevant_tx, ambiguous),
        "customer_reply": customer_reply(case_type, relevant_tx, ambiguous),
        "human_review_required": human_review_needed(case_type, verdict, severity, ambiguous),
        "confidence": confidence_for(case_type, verdict, relevant_tx, ambiguous),
        "reason_codes": reason_codes(case_type, verdict, relevant_tx, ambiguous),
    }


def enforce_output_safety(result: dict[str, Any]) -> dict[str, Any]:
    result["evidence_verdict"] = result["evidence_verdict"] if result["evidence_verdict"] in EVIDENCE else "insufficient_data"
    result["case_type"] = result["case_type"] if result["case_type"] in CASE_TYPES else "other"
    result["severity"] = result["severity"] if result["severity"] in SEVERITIES else "low"
    result["department"] = result["department"] if result["department"] in DEPARTMENTS else "customer_support"

    reply = safe_text(result.get("customer_reply"))
    forbidden_patterns = [
        "we will refund",
        "we will reverse",
        "refund is confirmed",
        "reversal is confirmed",
        "account will be unblocked",
        "send your otp",
        "share your otp",
        "share your pin",
        "send your pin",
        "password to us",
        "full card number",
    ]
    lower_reply = reply.lower()

    if any(pattern in lower_reply for pattern in forbidden_patterns):
        reply = "Your case will be reviewed through official support channels. Any eligible amount or action will be handled according to policy. Please do not share your PIN or OTP with anyone."

    result["customer_reply"] = reply
    return result