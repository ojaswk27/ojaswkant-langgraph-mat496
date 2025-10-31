from operator import add
from typing import List, Optional, Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from anthropic import Anthropic

# Initialize Anthropic client
client = Anthropic()

# Patient intake form structure
class PatientIntake(TypedDict):
    patient_id: str
    name: str
    age: int
    symptoms: List[str]
    vital_signs: Optional[dict]  # e.g., {"bp": "140/90", "temp": "101.2", "hr": "95"}
    urgency_score: Optional[int]  # 1-10, where 10 is most urgent
    chief_complaint: str
    medical_history: Optional[List[str]]

# ============================================
# URGENT CASE DETECTION SUB-GRAPH
# ============================================

class UrgentCaseState(TypedDict):
    cleaned_intakes: List[PatientIntake]
    urgent_cases: List[PatientIntake]
    urgent_summary: str
    processed_patients: List[str]

class UrgentCaseOutputState(TypedDict):
    urgent_summary: str
    processed_patients: List[str]

def identify_urgent_cases(state):
    """Filter patients with high urgency scores (8+)"""
    cleaned_intakes = state["cleaned_intakes"]
    urgent_cases = [
        intake for intake in cleaned_intakes
        if intake.get("urgency_score", 0) >= 8
    ]
    return {"urgent_cases": urgent_cases}

def generate_urgent_summary(state):
    """Generate triage summary using Claude"""
    urgent_cases = state["urgent_cases"]

    if not urgent_cases:
        return {
            "urgent_summary": "No urgent cases detected.",
            "processed_patients": []
        }

    cases_text = "\n\n".join([
        f"Patient ID: {c['patient_id']}\n"
        f"Name: {c['name']}, Age: {c['age']}\n"
        f"Chief Complaint: {c['chief_complaint']}\n"
        f"Symptoms: {', '.join(c['symptoms'])}\n"
        f"Urgency Score: {c['urgency_score']}/10\n"
        f"Vitals: {c.get('vital_signs', 'Not recorded')}"
        for c in urgent_cases
    ])

    prompt = f"""You are an ER triage nurse. Review these urgent cases and provide:
1. Immediate action recommendations
2. Priority ordering (most to least urgent)
3. Any red flags requiring specialist consultation

URGENT CASES:
{cases_text}

Provide a clear, actionable triage summary."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "urgent_summary": message.content[0].text,
        "processed_patients": [f"urgent-triage-{c['patient_id']}" for c in urgent_cases]
    }

# Build Urgent Case Detection sub-graph
urgent_builder = StateGraph(
    state_schema=UrgentCaseState,
    output_schema=UrgentCaseOutputState
)
urgent_builder.add_node("identify_urgent", identify_urgent_cases)
urgent_builder.add_node("generate_summary", generate_urgent_summary)
urgent_builder.add_edge(START, "identify_urgent")
urgent_builder.add_edge("identify_urgent", "generate_summary")
urgent_builder.add_edge("generate_summary", END)

# ============================================
# SYMPTOM PATTERN ANALYSIS SUB-GRAPH
# ============================================

class SymptomPatternState(TypedDict):
    cleaned_intakes: List[PatientIntake]
    pattern_analysis: str
    pattern_report: str
    processed_patients: List[str]

class SymptomPatternOutputState(TypedDict):
    pattern_report: str
    processed_patients: List[str]

def analyze_symptom_patterns(state):
    """Analyze symptom patterns using Claude"""
    cleaned_intakes = state["cleaned_intakes"]

    if not cleaned_intakes:
        return {
            "pattern_analysis": "No patients to analyze.",
            "processed_patients": []
        }

    patients_text = "\n".join([
        f"Patient {i['patient_id']}: {', '.join(i['symptoms'])} (Age: {i['age']})"
        for i in cleaned_intakes
    ])

    prompt = f"""You are an epidemiologist analyzing patient intake data. Identify:
1. Common symptom patterns
2. Potential disease clusters or outbreaks
3. Age group correlations
4. Recommendations for public health monitoring

PATIENT DATA:
{patients_text}

Provide epidemiological insights."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "pattern_analysis": message.content[0].text,
        "processed_patients": [f"pattern-analysis-{i['patient_id']}" for i in cleaned_intakes]
    }

def generate_report(state):
    """Format report for clinical staff"""
    pattern_analysis = state["pattern_analysis"]

    report = f"""📊 SYMPTOM PATTERN REPORT
{'=' * 50}

{pattern_analysis}

{'=' * 50}
Report generated for clinical review and public health monitoring."""

    return {"pattern_report": report}

# Build Symptom Pattern sub-graph
pattern_builder = StateGraph(
    SymptomPatternState,
    output_schema=SymptomPatternOutputState
)
pattern_builder.add_node("analyze_patterns", analyze_symptom_patterns)
pattern_builder.add_node("generate_report", generate_report)
pattern_builder.add_edge(START, "analyze_patterns")
pattern_builder.add_edge("analyze_patterns", "generate_report")
pattern_builder.add_edge("generate_report", END)

# ============================================
# ENTRY GRAPH (MAIN WORKFLOW)
# ============================================

class EntryGraphState(TypedDict):
    raw_intakes: List[PatientIntake]
    cleaned_intakes: List[PatientIntake]
    urgent_summary: str  # From Urgent Case Detection
    pattern_report: str  # From Symptom Pattern Analysis
    processed_patients: Annotated[List[str], add]  # Accumulated from both sub-graphs

def validate_and_clean(state):
    """Validate and normalize patient data"""
    raw_intakes = state["raw_intakes"]

    # In a real system, you'd:
    # - Validate required fields
    # - Normalize formats
    # - Clean data
    # For demo, we just pass through
    cleaned_intakes = raw_intakes

    return {"cleaned_intakes": cleaned_intakes}

# Build entry graph
entry_builder = StateGraph(EntryGraphState)
entry_builder.add_node("validate_and_clean", validate_and_clean)
entry_builder.add_node("urgent_detection", urgent_builder.compile())
entry_builder.add_node("symptom_analysis", pattern_builder.compile())

# Define workflow
entry_builder.add_edge(START, "validate_and_clean")
entry_builder.add_edge("validate_and_clean", "urgent_detection")
entry_builder.add_edge("validate_and_clean", "symptom_analysis")
entry_builder.add_edge("urgent_detection", END)
entry_builder.add_edge("symptom_analysis", END)

# Compile the complete graph
graph = entry_builder.compile()
