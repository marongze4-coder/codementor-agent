from langgraph.graph import END, START, StateGraph

from backend.agents.assignment.nodes import (
    aggregate_assignment_node,
    load_assignment_node,
    run_functional_tests_node,
    run_quality_review_node,
    save_assignment_review_node,
)
from backend.agents.assignment.state import AssignmentState


def build_assignment_graph():
    builder = StateGraph(AssignmentState)
    builder.add_node("load_assignment", load_assignment_node)
    builder.add_node("run_functional_tests", run_functional_tests_node)
    builder.add_node("run_quality_review", run_quality_review_node)
    builder.add_node("aggregate", aggregate_assignment_node)
    builder.add_node("save_review", save_assignment_review_node)

    builder.add_edge(START, "load_assignment")
    builder.add_edge("load_assignment", "run_functional_tests")
    builder.add_edge("load_assignment", "run_quality_review")
    builder.add_edge("run_functional_tests", "aggregate")
    builder.add_edge("run_quality_review", "aggregate")
    builder.add_edge("aggregate", "save_review")
    builder.add_edge("save_review", END)
    return builder.compile()
