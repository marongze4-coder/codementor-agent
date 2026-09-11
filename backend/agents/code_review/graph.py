from langgraph.graph import END, START, StateGraph

from backend.agents.code_review.nodes import (
    aggregate_review_node,
    analyze_structure_node,
    load_source_node,
    run_dimension_reviews_node,
    save_review_node,
)
from backend.agents.code_review.state import CodeReviewState


def build_code_review_graph():
    builder = StateGraph(CodeReviewState)
    builder.add_node("load_source", load_source_node)
    builder.add_node("analyze_structure", analyze_structure_node)
    builder.add_node("run_dimension_reviews", run_dimension_reviews_node)
    builder.add_node("aggregate_review", aggregate_review_node)
    builder.add_node("save_review", save_review_node)

    builder.add_edge(START, "load_source")
    builder.add_edge("load_source", "analyze_structure")
    builder.add_edge("analyze_structure", "run_dimension_reviews")
    builder.add_edge("run_dimension_reviews", "aggregate_review")
    builder.add_edge("aggregate_review", "save_review")
    builder.add_edge("save_review", END)
    return builder.compile()
