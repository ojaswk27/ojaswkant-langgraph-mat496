from operator import add
from typing import List, Optional, Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from anthropic import Anthropic

# Initialize Anthropic client
client = Anthropic()


# The structure of the logs
class Log(TypedDict):
    id: str
    question: str
    docs: Optional[List]
    answer: str
    grade: Optional[int]
    grader: Optional[str]
    feedback: Optional[str]


# Failure Analysis Sub-graph
class FailureAnalysisState(TypedDict):
    cleaned_logs: List[Log]
    failures: List[Log]
    fa_summary: str
    processed_logs: List[str]


class FailureAnalysisOutputState(TypedDict):
    fa_summary: str
    processed_logs: List[str]


def get_failures(state):
    """Get logs that contain a failure (have a grade)"""
    cleaned_logs = state["cleaned_logs"]
    failures = [log for log in cleaned_logs if "grade" in log]
    return {"failures": failures}


def generate_failure_summary(state):
    """Generate summary of failures using Claude"""
    failures = state["failures"]

    if not failures:
        return {
            "fa_summary": "No failures detected.",
            "processed_logs": []
        }

    # Create a prompt for Claude to analyze failures
    failure_text = "\n\n".join([
        f"Log ID: {f['id']}\nQuestion: {f['question']}\n"
        f"Answer: {f['answer']}\nGrade: {f['grade']}\n"
        f"Grader: {f['grader']}\nFeedback: {f['feedback']}"
        for f in failures
    ])

    prompt = f"""Analyze these failure logs and provide a concise summary of the main issues:

{failure_text}

Provide a brief, actionable summary of the key problems."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    fa_summary = message.content[0].text

    return {
        "fa_summary": fa_summary,
        "processed_logs": [f"failure-analysis-on-log-{failure['id']}" for failure in failures]
    }


fa_builder = StateGraph(
    state_schema=FailureAnalysisState,
    output_schema=FailureAnalysisOutputState
)
fa_builder.add_node("get_failures", get_failures)
fa_builder.add_node("generate_summary", generate_failure_summary)
fa_builder.add_edge(START, "get_failures")
fa_builder.add_edge("get_failures", "generate_summary")
fa_builder.add_edge("generate_summary", END)


# Question Summarization subgraph
class QuestionSummarizationState(TypedDict):
    cleaned_logs: List[Log]
    qs_summary: str
    report: str
    processed_logs: List[str]


class QuestionSummarizationOutputState(TypedDict):
    report: str
    processed_logs: List[str]


def generate_question_summary(state):
    """Summarize the questions from logs using Claude"""
    cleaned_logs = state["cleaned_logs"]

    if not cleaned_logs:
        return {
            "qs_summary": "No questions to analyze.",
            "processed_logs": []
        }

    # Extract questions
    questions_text = "\n".join([
        f"{i + 1}. {log['question']}"
        for i, log in enumerate(cleaned_logs)
    ])

    prompt = f"""Analyze these user questions and provide a summary of the main topics and themes:

{questions_text}

Provide a concise summary of what topics users are asking about."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    summary = message.content[0].text

    return {
        "qs_summary": summary,
        "processed_logs": [f"summary-on-log-{log['id']}" for log in cleaned_logs]
    }


def send_to_slack(state):
    """Generate a report (in real system, this would send to Slack)"""
    qs_summary = state["qs_summary"]

    # In a real system, you'd send this to Slack
    # For demo purposes, we just format it as a report
    report = f"""📊 Question Analysis Report

{qs_summary}

(In production, this would be sent to Slack)"""

    return {"report": report}


qs_builder = StateGraph(
    QuestionSummarizationState,
    output_schema=QuestionSummarizationOutputState
)
qs_builder.add_node("generate_summary", generate_question_summary)
qs_builder.add_node("send_to_slack", send_to_slack)
qs_builder.add_edge(START, "generate_summary")
qs_builder.add_edge("generate_summary", "send_to_slack")
qs_builder.add_edge("send_to_slack", END)


# Entry Graph
class EntryGraphState(TypedDict):
    raw_logs: List[Log]
    cleaned_logs: List[Log]
    fa_summary: str  # From Failure Analysis sub-graph
    report: str  # From Question Summarization sub-graph
    processed_logs: Annotated[List[str], add]  # Accumulated from BOTH sub-graphs


def clean_logs(state):
    """Clean/preprocess the raw logs"""
    raw_logs = state["raw_logs"]
    # In a real system, you'd do data cleaning here
    # For demo, we just pass through
    cleaned_logs = raw_logs
    return {"cleaned_logs": cleaned_logs}


entry_builder = StateGraph(EntryGraphState)
entry_builder.add_node("clean_logs", clean_logs)
entry_builder.add_node("question_summarization", qs_builder.compile())
entry_builder.add_node("failure_analysis", fa_builder.compile())

# Flow: START -> clean_logs -> (failure_analysis + question_summarization) -> END
entry_builder.add_edge(START, "clean_logs")
entry_builder.add_edge("clean_logs", "failure_analysis")
entry_builder.add_edge("clean_logs", "question_summarization")
entry_builder.add_edge("failure_analysis", END)
entry_builder.add_edge("question_summarization", END)

graph = entry_builder.compile()
