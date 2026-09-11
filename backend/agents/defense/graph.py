from langgraph.graph import END, START, StateGraph

from backend.agents.defense.nodes import (
    advance_stage_node,
    generate_defense_report_node,
    generate_defense_response_node,
    load_defense_context_node,
    route_after_stage,
    save_defense_turn_node,
)
from backend.agents.defense.state import DefenseState


def build_defense_graph():
    builder = StateGraph(DefenseState)
    builder.add_node("load_context", load_defense_context_node)
    builder.add_node("advance_stage", advance_stage_node)
    builder.add_node("respond", generate_defense_response_node)
    builder.add_node("report", generate_defense_report_node)
    builder.add_node("save", save_defense_turn_node)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "advance_stage")
    builder.add_conditional_edges(
        "advance_stage",
        route_after_stage,
        {"respond": "respond", "report": "report"},
    )
    builder.add_edge("respond", "save")
    builder.add_edge("report", "save")
    builder.add_edge("save", END)
    return builder.compile()
