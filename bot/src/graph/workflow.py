"""LangGraph workflow topology.

Two compiled graphs are exported:

  single_stock_graph — used by bot handlers for /decide, /choose
    START → data_agent → (fundamental_agent ║ sentiment_agent) → decision_agent → END

  graph — full graph with intent routing, used as the main entry point
    START → route_intent
              ├─► (single)    single_stock_graph nodes
              └─► (portfolio) portfolio_agent → END
"""

from langgraph.graph import END, START, StateGraph

from ..agents.data import data_agent
from ..agents.decision import decision_agent
from ..agents.fundamental import fundamental_agent
from ..agents.portfolio import portfolio_agent
from ..agents.sentiment import sentiment_agent
from ..state import AnalysisState


# ── Routing edge ──────────────────────────────────────────────────────────────


def route_intent(state: AnalysisState) -> str:
    """Conditional edge: branch on analysis mode."""
    if state.get("error"):
        return END
    return "data_agent" if state["mode"] == "single" else "portfolio_agent"


# ── After data_agent: fan out to both analysis agents in parallel ─────────────


def after_data(state: AnalysisState) -> list[str]:
    """Fan-out edge: run fundamental and sentiment agents in parallel."""
    if state.get("error"):
        return [END]
    return ["fundamental_agent", "sentiment_agent"]


# ── Single-stock subgraph (reused by portfolio_agent) ────────────────────────


def build_single_stock_graph() -> StateGraph:
    builder = StateGraph(AnalysisState)

    builder.add_node("data_agent", data_agent)
    builder.add_node("fundamental_agent", fundamental_agent)
    builder.add_node("sentiment_agent", sentiment_agent)
    builder.add_node("decision_agent", decision_agent)

    builder.add_edge(START, "data_agent")
    builder.add_conditional_edges(
        "data_agent",
        after_data,
        {
            "fundamental_agent": "fundamental_agent",
            "sentiment_agent": "sentiment_agent",
            END: END,
        },
    )
    builder.add_edge("fundamental_agent", "decision_agent")
    builder.add_edge("sentiment_agent", "decision_agent")
    builder.add_edge("decision_agent", END)

    return builder.compile()


# ── Full graph (main entry point) ─────────────────────────────────────────────


def build_graph() -> StateGraph:
    builder = StateGraph(AnalysisState)

    builder.add_node("data_agent", data_agent)
    builder.add_node("fundamental_agent", fundamental_agent)
    builder.add_node("sentiment_agent", sentiment_agent)
    builder.add_node("decision_agent", decision_agent)
    builder.add_node("portfolio_agent", portfolio_agent)

    builder.add_conditional_edges(
        START,
        route_intent,
        {
            "data_agent": "data_agent",
            "portfolio_agent": "portfolio_agent",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "data_agent",
        after_data,
        {
            "fundamental_agent": "fundamental_agent",
            "sentiment_agent": "sentiment_agent",
            END: END,
        },
    )
    builder.add_edge("fundamental_agent", "decision_agent")
    builder.add_edge("sentiment_agent", "decision_agent")
    builder.add_edge("decision_agent", END)
    builder.add_edge("portfolio_agent", END)

    return builder.compile()


# Exported compiled graphs
single_stock_graph = build_single_stock_graph()
graph = build_graph()
