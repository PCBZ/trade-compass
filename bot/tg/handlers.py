"""Telegram command handlers.

/decide NVDA    → single-stock analysis
/portfolio      → full portfolio analysis
/model          → inline keyboard to select LLM model
/help           → list commands
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import get_llm_models, is_valid_model
from bot.graph.workflow import graph, single_stock_graph
from bot.tools.portfolio_api import get_preferences, get_holdings
import httpx
import os


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_decision(ticker: str, decision: dict) -> str:
    verdict     = decision.get("verdict", "N/A")
    confidence  = decision.get("confidence", "")
    thesis      = decision.get("thesis", "")
    assumptions = decision.get("key_assumptions", [])
    stop_loss   = decision.get("stop_loss")
    target      = decision.get("target_price")

    emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(verdict, "⚪")

    lines = [
        f"{emoji} *{ticker}* — {verdict} ({confidence})",
        f"_{thesis}_",
    ]
    if assumptions:
        lines.append("\n*Key assumptions:*")
        for a in assumptions:
            lines.append(f"  • {a}")
    if stop_loss:
        lines.append(f"\n🛑 Stop-loss: ${stop_loss:.2f}")
    if target:
        lines.append(f"🎯 Target: ${target:.2f}")

    return "\n".join(lines)


def _format_portfolio_summary(summary: dict) -> str:
    verdicts = summary.get("verdicts", [])
    risks    = summary.get("concentration_risk", [])
    analyzed = summary.get("analyzed_count", 0)
    total    = summary.get("holdings_count", 0)

    lines = [f"📁 *Portfolio Analysis* ({analyzed}/{total} stocks)\n"]

    for v in verdicts:
        emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(v.get("verdict"), "⚪")
        lines.append(
            f"{emoji} *{v['ticker']}* — {v.get('verdict')} ({v.get('confidence', '')})"
        )
        if v.get("thesis"):
            lines.append(f"   _{v['thesis'][:120]}..._")

    if risks:
        lines.append("\n⚠️ *Concentration Risk*")
        for r in risks:
            lines.append(f"  • {r['ticker']} {r['weight_pct']}% — {r['flag']}")

    return "\n".join(lines)


async def _get_initial_state(ticker: str | None, mode: str) -> dict:
    preferences = await get_preferences()
    holdings    = await get_holdings()
    return {
        "ticker": ticker,
        "mode": mode,
        "preferences": preferences,
        "holdings": holdings,
        "raw_data": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "decision": None,
        "portfolio_summary": {},
        "error": None,
    }


# ── Command handlers ──────────────────────────────────────────────────────────

async def handle_decide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/decide NVDA — single-stock analysis."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/decide TICKER` e.g. `/decide NVDA`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper()
    await update.message.reply_text(f"🔍 Analysing *{ticker}*...", parse_mode="Markdown")

    try:
        state = await _get_initial_state(ticker, "single")
        result = await single_stock_graph.ainvoke(state)

        if result.get("error"):
            await update.message.reply_text(f"❌ Error: {result['error']}")
            return

        text = _format_decision(ticker, result.get("decision") or {})
        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ Analysis failed: {exc}")


async def handle_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/portfolio — analyse all STOCK holdings."""
    await update.message.reply_text("📁 Analysing your portfolio...", parse_mode="Markdown")

    try:
        state = await _get_initial_state(None, "portfolio")
        result = await graph.ainvoke(state)

        if result.get("error"):
            await update.message.reply_text(f"❌ Error: {result['error']}")
            return

        summary = result.get("portfolio_summary") or {}
        if not summary.get("verdicts"):
            await update.message.reply_text("No STOCK positions found.")
            return

        text = _format_portfolio_summary(summary)
        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ Portfolio analysis failed: {exc}")


async def handle_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/model — show inline keyboard with available LLM models."""
    preferences = await get_preferences()
    current_model = preferences.get("llm_model", "")

    models = get_llm_models()
    keyboard = []
    for m in models:
        label = f"{'✅ ' if m['id'] == current_model else ''}{m['name']} — {m['description']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"model:{m['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Select LLM model for analysis:*",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline keyboard callback — saves selected model to preferences."""
    query = update.callback_query
    await query.answer()

    model_id = query.data.replace("model:", "")
    if not is_valid_model(model_id):
        await query.edit_message_text("❌ Invalid model selection.")
        return

    # Save to preferences via REST API
    api_url = os.environ.get("API_URL", "").rstrip("/")
    api_key = os.environ.get("API_KEY", "")
    try:
        async with httpx.AsyncClient() as client:
            prefs = (
                await client.get(
                    f"{api_url}/preferences",
                    headers={"X-API-Key": api_key},
                    timeout=10,
                )
            ).json()
            prefs["llm_model"] = model_id
            await client.put(
                f"{api_url}/preferences",
                json=prefs,
                headers={"X-API-Key": api_key},
                timeout=10,
            )
    except Exception as exc:  # noqa: BLE001
        await query.edit_message_text(f"❌ Failed to save model: {exc}")
        return

    models = get_llm_models()
    name = next((m["name"] for m in models if m["id"] == model_id), model_id)
    await query.edit_message_text(f"✅ Model set to *{name}*", parse_mode="Markdown")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — list available commands."""
    text = (
        "📊 *trade-compass*\n\n"
        "/decide `TICKER` — analyse a single stock\n"
        "/portfolio — analyse all your holdings\n"
        "/model — select LLM model\n"
        "/help — show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
