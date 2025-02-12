from flask import Flask, request, jsonify, Response, send_from_directory
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional
import uuid
import json
import os
import shutil
from pathlib import Path
from abc import ABC, abstractmethod
import threading
import time
from queue import PriorityQueue

# --- Gemini Integration ---
import google.generativeai as genai  # Placeholder: install and configure this package
# --- End Gemini Integration ---

# ---------------------------
# Configuration and Constants
# ---------------------------

BASE_DATA_DIR = "data"
CASES_DIR = os.path.join(BASE_DATA_DIR, "cases")
DOCUMENTS_DIR = os.path.join(BASE_DATA_DIR, "documents")
CONFIG_DIR = "config"
WORKFLOWS_DIR = os.path.join(CONFIG_DIR, "workflows")  # Subdirectory for workflows
PROMPTS_DIR = os.path.join(CONFIG_DIR, "prompts")      # Subdirectory for prompts

for dir_path in [BASE_DATA_DIR, CASES_DIR, DOCUMENTS_DIR, CONFIG_DIR, WORKFLOWS_DIR, PROMPTS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ---------------------------
# Data Models (Serializable)
# ---------------------------

@dataclass
class Document:
    id: str
    case_id: str
    type: str
    upload_date: str
    content_path: Optional[str] = None
    content: Optional[str] = None
    analysis: Dict[str, Any] = field(default_factory=dict)
    stage: str = ""
    ai_suggestions: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProcessStep:
    timestamp: str
    event: str
    details: Dict[str, Any] = field(default_factory=dict)
    ai_enrichment: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProcessFlow:
    steps: List[ProcessStep] = field(default_factory=list)
    pathways: List[Dict[str, Any]] = field(default_factory=list)
    ai_guidance: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Case:
    id: str
    workflow_id: str
    current_stage: str
    status: str
    documents: List[str] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    process_flow: ProcessFlow = field(default_factory=ProcessFlow)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkflowStage:
    id: str
    name: str
    description: str
    required_document_types: List[str] = field(default_factory=list)
    next_stages: List[str] = field(default_factory=list)
    widgets: List[Dict[str, Any]] = field(default_factory=list)
    ai_config: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkflowDefinition:
    id: str
    name: str
    description: str
    stages: Dict[str, WorkflowStage]
    initial_stage: str
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

# ---------------------------
# Data Access and Persistence
# ---------------------------

def generate_id() -> str:
    return str(uuid.uuid4())

def save_json(filepath: str, data: Any):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

def load_json(filepath: str) -> Any:
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return None

def save_document_content(case_id: str, doc_id: str, file_content, filename: str) -> str:
    case_dir = os.path.join(DOCUMENTS_DIR, case_id)
    os.makedirs(case_dir, exist_ok=True)
    file_extension = os.path.splitext(filename)[1]
    filepath = os.path.join(case_dir, f"{doc_id}{file_extension}")
    if isinstance(file_content, bytes):
        with open(filepath, 'wb') as f:
            f.write(file_content)
    else:
        with open(filepath, 'w') as f:
            f.write(file_content)
    return os.path.relpath(filepath, BASE_DATA_DIR)

def load_document_content(content_path: str):
    absolute_path = os.path.join(BASE_DATA_DIR, content_path)
    _, ext = os.path.splitext(absolute_path)
    try:
        if ext.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.pdf']:
            with open(absolute_path, 'rb') as f:
                return f.read()
        else:
            with open(absolute_path, 'r') as f:
                return f.read()
    except FileNotFoundError:
        return None

def save_case(case: Case):
    case_filepath = os.path.join(CASES_DIR, f"{case.id}.json")
    save_json(case_filepath, asdict(case))

def load_case(case_id: str) -> Optional[Case]:
    case_filepath = os.path.join(CASES_DIR, f"{case_id}.json")
    case_data = load_json(case_filepath)
    if case_data:
        if "process_flow" in case_data:
            steps = [ProcessStep(**step) for step in case_data["process_flow"].get("steps", [])]
            pathways = case_data["process_flow"].get("pathways", [])
            ai_guidance = case_data["process_flow"].get("ai_guidance", {})
            case_data["process_flow"] = ProcessFlow(steps=steps, pathways=pathways, ai_guidance=ai_guidance)
        return Case(**case_data)
    return None

def get_or_create_case(case_id: str, workflow_id: str) -> Case:
    case = load_case(case_id)
    if case:
        return case
    workflow_def = load_workflow(workflow_id)
    if not workflow_def:
        raise ValueError(f"Workflow not found: {workflow_id}")
    new_case = Case(
        id=case_id,
        workflow_id=workflow_id,
        current_stage=workflow_def.initial_stage,
        status="active",
        documents=[],
        timeline=[],
        process_flow=ProcessFlow()
    )
    save_case(new_case)
    return new_case

def save_document(document: Document):
    doc_filepath = os.path.join(DOCUMENTS_DIR, f"{document.id}.json")
    save_json(doc_filepath, asdict(document))

def load_document(document_id: str) -> Optional[Document]:
    doc_filepath = os.path.join(DOCUMENTS_DIR, f"{document_id}.json")
    doc_data = load_json(doc_filepath)
    if doc_data:
        return Document(**doc_data)
    return None

def add_document_to_case(case: Case, document: Document, event: str):
    case.documents.append(document.id)
    save_document(document)
    case.timeline.append({
        "timestamp": datetime.now().isoformat(),
        "event": event
    })
    save_case(case)

def save_workflow(workflow: WorkflowDefinition):
    workflow_filepath = os.path.join(WORKFLOWS_DIR, f"workflow_{workflow.id}.json")
    save_json(workflow_filepath, asdict(workflow))

def load_workflow(workflow_id: str) -> Optional[WorkflowDefinition]:
    workflow_filepath = os.path.join(WORKFLOWS_DIR, f"workflow_{workflow_id}.json")
    workflow_data = load_json(workflow_filepath)
    if workflow_data:
        stages = {sid: WorkflowStage(**sdata) for sid, sdata in workflow_data.get('stages', {}).items()}
        workflow_data['stages'] = stages
        return WorkflowDefinition(**workflow_data)
    return None

def load_default_workflows():
    eviction_workflow_path = os.path.join(WORKFLOWS_DIR, "workflow_eviction.json")
    if not os.path.exists(eviction_workflow_path):
        eviction_workflow = WorkflowDefinition(
            id="eviction",
            name="Eviction Process",
            description="Standard eviction workflow",
            initial_stage="notice",
            stages={
                "notice": WorkflowStage(
                    id="notice",
                    name="Notice Stage",
                    description="Initial notice period.",
                    required_document_types=["agency_document"],
                    next_stages=["complaint_filed", "resolved"],
                    widgets=[{"type": "upload", "label": "Upload Notice Document", "document_type": "agency_document"},
                             {"type": "input", "label": "Service Date", "field_name": "service_date"}]
                ),
                "complaint_filed": WorkflowStage(
                    id="complaint_filed",
                    name="Complaint Filed Stage",
                    description="Complaint has been filed.",
                    required_document_types=["uploaded_document", "supporting_data"],
                    next_stages=["default", "answer_filed", "motion_filed"],
                    widgets=[{"type": "upload", "label": "Upload Complaint", "document_type": "uploaded_document"},
                             {"type": "checkbox", "label": "Verify Service", "field_name": "service_verified"}]
                ),
                "resolved": WorkflowStage(
                    id="resolved",
                    name="Resolved Stage",
                    description="Case resolved.",
                    next_stages=[],
                    widgets=[]
                ),
                "default": WorkflowStage(
                    id="default",
                    name="Default Stage",
                    description="Default judgement pathway.",
                    next_stages=[],
                    widgets=[]
                ),
                "answer_filed": WorkflowStage(
                    id="answer_filed",
                    name="Answer Filed Stage",
                    description="Answer filed by defendant.",
                    next_stages=[],
                    widgets=[]
                ),
                "motion_filed": WorkflowStage(
                    id="motion_filed",
                    name="Motion Filed Stage",
                    description="Motion has been filed.",
                    next_stages=[],
                    widgets=[]
                ),
            }
        )
        save_workflow(eviction_workflow)

load_default_workflows()

# ---------------------------
# Prompt Management
# ---------------------------

def load_prompt(prompt_id: str) -> Optional[str]:
    prompt_filepath = os.path.join(PROMPTS_DIR, f"{prompt_id}.txt")
    prompt_content = load_json(prompt_filepath)
    if prompt_content is None:
        try:
            with open(prompt_filepath, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return None
    else:
        return prompt_content.get('prompt')

def save_prompt(prompt_id: str, prompt_text: str, format='txt'):
    if format == 'json':
        prompt_filepath = os.path.join(PROMPTS_DIR, f"{prompt_id}.json")
        save_json(prompt_filepath, {'prompt': prompt_text})
    else:
        prompt_filepath = os.path.join(PROMPTS_DIR, f"{prompt_id}.txt")
        with open(prompt_filepath, 'w') as f:
            f.write(prompt_text)

def load_default_prompts():
    prompt_analyze_document = load_prompt("analyze_document")
    if not prompt_analyze_document:
        prompt_analyze_document_text = """
Analyze the following document content and extract key information relevant to a case management system.
Identify and extract entities such as:
- Dates
- Names of people and organizations
- Locations
- Document type (if discernible)
- Key actions or events described
Output the extracted information in JSON format. Use null for missing fields.

Document Content:
{{document_content}}
"""
        save_prompt("analyze_document", prompt_analyze_document_text)
    prompt_suggest_next_steps = load_prompt("suggest_next_steps")
    if not prompt_suggest_next_steps:
        prompt_suggest_next_steps_text = """
Based on the current state of this case and the documents provided, suggest 2-3 logical next steps.
Consider the current stage, required documents, and available pathways from the workflow.

Case ID: {{case_id}}
Current Stage: {{current_stage}}
Workflow Definition ID: {{workflow_id}}
Documents (by type): {{document_types}}

Output your suggestions as a JSON list where each suggestion is an object with 'stage_id', 'label', and 'reason'.
"""
        save_prompt("suggest_next_steps", prompt_suggest_next_steps_text)
    prompt_suggest_section = load_prompt("suggest_section")
    if not prompt_suggest_section:
        prompt_suggest_section_text = """
Below is an XML summary of the pathways and structures for a section of the case:

{{xml_summary}}

The goal for this section is: {{goal}}.
The intended conclusion is: {{intended_conclusion}}.
Case ID: {{case_id}}
Current Stage: {{current_stage}}

Based on the provided information, please output an XML response that either:
- Proposes a crucial action,
- Suggests gathering a specific datapoint,
- Reroutes to an alternative pathway,
- Or indicates that no further action is needed.

Ensure your response is valid XML with a root element <suggestion> and appropriate child elements.
"""
        save_prompt("suggest_section", prompt_suggest_section_text)

load_default_prompts()

# ---------------------------
# Gemini Integration Functions
# ---------------------------

def initialize_gemini_api():
    gemini_api_key = os.environ.get('GEMINI_API_KEY') or 'YOUR_API_KEY_HERE'
    if gemini_api_key == 'YOUR_API_KEY_HERE':
        print("Warning: Gemini API key is not configured. AI features will not work.")
        return None
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro')
    return model

gemini_model = initialize_gemini_api()

def analyze_document_with_gemini(document_content: str, prompt_template: str) -> Optional[Dict[str, Any]]:
    if gemini_model is None:
        return {"error": "Gemini API not initialized."}
    prompt_text = prompt_template.replace("{{document_content}}", document_content)
    try:
        response = gemini_model.generate_content(prompt_text)
        response.resolve()
        if response.parts and response.parts[0].text:
            ai_response_text = response.parts[0].text
            try:
                ai_data = json.loads(ai_response_text)
                return ai_data
            except json.JSONDecodeError:
                print(f"Warning: Gemini response was not valid JSON: {ai_response_text}")
                return {"raw_response": ai_response_text, "error": "Non-JSON response from AI"}
        else:
            return {"error": "Empty response from AI"}
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {"error": f"Gemini API call failed: {e}"}

def suggest_next_steps_with_gemini(case: Case, workflow_def: WorkflowDefinition, prompt_template: str) -> Optional[List[Dict[str, str]]]:
    if gemini_model is None:
        return [{"error": "Gemini API not initialized."}]
    document_types_in_case = []
    for doc_id in case.documents:
        doc = load_document(doc_id)
        if doc:
            document_types_in_case.append(doc.type)
    prompt_text = prompt_template.replace("{{case_id}}", case.id)
    prompt_text = prompt_text.replace("{{current_stage}}", case.current_stage)
    prompt_text = prompt_text.replace("{{workflow_id}}", workflow_def.id)
    prompt_text = prompt_text.replace("{{document_types}}", str(document_types_in_case))
    try:
        response = gemini_model.generate_content(prompt_text)
        response.resolve()
        if response.parts and response.parts[0].text:
            ai_response_text = response.parts[0].text
            try:
                suggestions = json.loads(ai_response_text)
                if isinstance(suggestions, list):
                    return suggestions
                else:
                    print(f"Warning: Gemini response was not a JSON list: {ai_response_text}")
                    return [{"error": "Non-list JSON response from AI", "raw_response": ai_response_text}]
            except json.JSONDecodeError:
                print(f"Warning: Gemini response was not valid JSON: {ai_response_text}")
                return [{"error": "Non-JSON response from AI", "raw_response": ai_response_text}]
        else:
            return [{"error": "Empty response from AI"}]
    except Exception as e:
        print(f"Gemini API Error (suggest_next_steps): {e}")
        return [{"error": f"Gemini API call failed: {e}"}]

def suggest_section_with_gemini(case: Case, xml_summary: str, goal: str, intended_conclusion: str, prompt_template: str) -> Optional[str]:
    if gemini_model is None:
        return "<suggestion>Error: Gemini API not initialized.</suggestion>"
    prompt_text = prompt_template.replace("{{xml_summary}}", xml_summary)
    prompt_text = prompt_text.replace("{{goal}}", goal)
    prompt_text = prompt_text.replace("{{intended_conclusion}}", intended_conclusion)
    prompt_text = prompt_text.replace("{{case_id}}", case.id)
    prompt_text = prompt_text.replace("{{current_stage}}", case.current_stage)
    try:
        response = gemini_model.generate_content(prompt_text)
        response.resolve()
        if response.parts and response.parts[0].text:
            return response.parts[0].text
        else:
            return "<suggestion>Error: Empty response from AI</suggestion>"
    except Exception as e:
        return f"<suggestion>Error: Gemini API call failed: {e}</suggestion>"

# ---------------------------
# Workflow Logic (Abstract Base Class)
# ---------------------------

class WorkflowEngine(ABC):
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.workflow_def = load_workflow(self.workflow_id)
        if not self.workflow_def:
            raise ValueError(f"Workflow definition not found: {workflow_id}")

    @abstractmethod
    def validate_stage_transition(self, case: Case, new_stage: str) -> bool:
        pass

    @abstractmethod
    def update_process_flow(self, case: Case, current_stage: WorkflowStage, event: str, details: dict = None):
        pass

class AIWorkflowEngine(WorkflowEngine):
    def validate_stage_transition(self, case: Case, new_stage: str) -> bool:
        current_stage = case.current_stage
        stage_info = self.workflow_def.stages.get(current_stage)
        if stage_info and new_stage in stage_info.next_stages:
            required_docs = stage_info.required_document_types
            case_docs = [load_document(doc_id) for doc_id in case.documents]
            return all(any(doc.type == req for doc in case_docs if doc) for req in required_docs)
        return False

    def update_process_flow(self, case: Case, current_stage: WorkflowStage, event: str, details: dict = None):
        step = ProcessStep(
            timestamp=datetime.now().isoformat(),
            event=event,
            details=details or {}
        )
        case.process_flow.steps.append(step)
        if current_stage:
            case.process_flow.pathways = [
                {"stage_id": next_stage_id, "label": self.workflow_def.stages[next_stage_id].name}
                for next_stage_id in current_stage.next_stages
            ]
        else:
            case.process_flow.pathways = []
        save_case(case)

# ---------------------------
# Task Queue and ML Execution System
# ---------------------------

@dataclass(order=True)
class Task:
    priority: int
    created_at: float = field(init=False, default_factory=time.time)
    id: str = field(compare=False, default_factory=generate_id)
    type: str = field(compare=False, default="")
    parameters: Dict[str, Any] = field(compare=False, default_factory=dict)
    speed: float = field(compare=False, default=1.0)
    status: str = field(compare=False, default="pending")
    result: Optional[Any] = field(compare=False, default=None)
    updated_at: str = field(compare=False, default_factory=lambda: datetime.now().isoformat())

class TaskQueue:
    def __init__(self):
        self.tasks = PriorityQueue()
        self.lock = threading.Lock()

    def add_task(self, task: Task):
        with self.lock:
            self.tasks.put((-task.priority, time.time(), task))

    def get_next_task(self) -> Optional[Task]:
        with self.lock:
            if not self.tasks.empty():
                _, _, task = self.tasks.get()
                return task
        return None

    def list_tasks(self) -> List[Task]:
        tasks_list = []
        with self.lock:
            temp = []
            while not self.tasks.empty():
                item = self.tasks.get()
                temp.append(item)
                tasks_list.append(item[2])
            for item in temp:
                self.tasks.put(item)
        return tasks_list

task_queue = TaskQueue()
tasks_dict = {}

def execute_task(task: Task):
    try:
        task.status = "in_progress"
        task.updated_at = datetime.now().isoformat()
        processing_time = 2.0 / task.speed
        time.sleep(processing_time)
        if task.type == "bing_search":
            task.result = f"Simulated Bing search results for query: {task.parameters.get('query', '')}"
        elif task.type == "operator_query":
            task.result = "Simulated operator response: All systems operational."
        else:
            task.result = f"Task of type '{task.type}' completed successfully."
        task.status = "completed"
        task.updated_at = datetime.now().isoformat()
    except Exception as e:
        task.status = "failed"
        task.result = str(e)
        task.updated_at = datetime.now().isoformat()

def task_processor():
    while True:
        task = task_queue.get_next_task()
        if task:
            print(f"Processing task {task.id} (type: {task.type}, priority: {task.priority})")
            execute_task(task)
            print(f"Task {task.id} completed with result: {task.result}")
        else:
            time.sleep(1)

task_processor_thread = threading.Thread(target=task_processor, daemon=True)
task_processor_thread.start()

# ---------------------------
# Flask Endpoints
# ---------------------------

app = Flask(__name__)

@app.route('/')
def index():
    return "Logical Pathways API with AI, Task Queue, and ML Execution System"

@app.route('/api/case/<case_id>', methods=['GET'])
def get_case_details(case_id):
    case = load_case(case_id)
    if case:
        case_data = asdict(case)
        case_data['documents'] = [asdict(load_document(doc_id)) for doc_id in case.documents if load_document(doc_id)]
        return jsonify(case_data)
    return jsonify({"error": "Case not found"}), 404

@app.route('/api/case', methods=['POST'])
def create_case():
    data = request.get_json()
    case_id = data.get('case_id', generate_id())
    workflow_id = data.get('workflow_id', 'eviction')
    try:
        case = get_or_create_case(case_id, workflow_id)
        return jsonify({"message": "Case created", "case_id": case.id}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/upload-document', methods=['POST'])
def upload_document_route():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    case_id = request.form.get('case_id')
    document_type = request.form.get('document_type')
    workflow_id = request.form.get('workflow_id', 'eviction')
    analyze_with_ai = request.form.get('analyze_with_ai') == 'true'
    if not case_id or not document_type:
        return jsonify({"error": "Missing case_id or document_type"}), 400
    case = get_or_create_case(case_id, workflow_id)
    document_id = generate_id()
    content_path = save_document_content(case_id, document_id, file.read(), file.filename)
    document = Document(
        id=document_id,
        case_id=case_id,
        type=document_type,
        upload_date=datetime.now().isoformat(),
        content_path=content_path,
        stage=case.current_stage
    )
    if analyze_with_ai:
        prompt_analyze_doc = load_prompt("analyze_document")
        if prompt_analyze_doc:
            doc_content = load_document_content(content_path)
            if doc_content:
                analysis_result = analyze_document_with_gemini(doc_content, prompt_analyze_doc)
                document.analysis = analysis_result if analysis_result else {}
    workflow_engine = AIWorkflowEngine(workflow_id)
    current_stage_def = workflow_engine.workflow_def.stages.get(case.current_stage)
    add_document_to_case(case, document, f"Document {document.id} uploaded")
    workflow_engine.update_process_flow(case, current_stage_def, "document_uploaded", {"document_id": document.id})
    return jsonify({"message": "Document uploaded", "document_id": document.id, "ai_analysis": document.analysis if analyze_with_ai else None}), 201

@app.route('/api/documents/<case_id>/<document_id>', methods=['GET'])
def get_document_route(case_id, document_id):
    document = load_document(document_id)
    if not document or document.case_id != case_id:
        return jsonify({"error": "Document not found"}), 404
    if document.content_path:
        _, ext = os.path.splitext(document.content_path)
        mimetype = 'application/octet-stream'
        if ext.lower() in ['.jpg', '.jpeg']:
            mimetype = 'image/jpeg'
        elif ext.lower() == '.png':
            mimetype = 'image/png'
        elif ext.lower() == '.txt':
            mimetype = 'text/plain'
        elif ext.lower() == '.pdf':
            mimetype = 'application/pdf'
        return send_from_directory(os.path.join(BASE_DATA_DIR, os.path.dirname(document.content_path)), os.path.basename(document.content_path), mimetype=mimetype)
    elif document.content:
        return Response(document.content, mimetype='text/plain')
    else:
        return jsonify({"error": "Document content not available"}), 404

@app.route('/api/validate-transition', methods=['POST'])
def validate_transition_route():
    data = request.get_json()
    case_id = data.get('case_id')
    proposed_stage = data.get('new_stage')
    workflow_id = data.get('workflow_id', 'eviction')
    if not case_id or not proposed_stage:
        return jsonify({"error": "Missing case_id or new_stage"}), 400
    case = load_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    workflow_engine = AIWorkflowEngine(workflow_id)
    if workflow_engine.validate_stage_transition(case, proposed_stage):
        previous_stage = case.current_stage
        case.current_stage = proposed_stage
        case.timeline.append({
            "timestamp": datetime.now().isoformat(),
            "event": f"Stage changed from {previous_stage} to {proposed_stage}"
        })
        current_stage_def = workflow_engine.workflow_def.stages.get(case.current_stage)
        workflow_engine.update_process_flow(case, current_stage_def, "stage_transition", {"from": previous_stage, "to": proposed_stage})
        save_case(case)
        return jsonify({"valid": True, "new_stage": proposed_stage})
    else:
        current_stage_def = workflow_engine.workflow_def.stages.get(case.current_stage)
        missing_docs = []
        if current_stage_def:
            required_docs = current_stage_def.required_document_types
            case_docs = [load_document(doc_id) for doc_id in case.documents]
            for req_type in required_docs:
                if not any(doc.type == req_type for doc in case_docs if doc):
                    missing_docs.append(req_type)
        return jsonify({"valid": False, "missing_requirements": missing_docs}), 400

@app.route('/api/workflows', methods=['GET'])
def list_workflows():
    workflow_files = [f for f in os.listdir(WORKFLOWS_DIR) if f.startswith("workflow_") and f.endswith(".json")]
    workflows = []
    for filename in workflow_files:
        workflow_id = filename[len("workflow_"):-len(".json")]
        wf = load_workflow(workflow_id)
        if wf:
            workflows.append({"id": wf.id, "name": wf.name, "description": wf.description})
    return jsonify(workflows)

@app.route('/api/workflows/<workflow_id>', methods=['GET'])
def get_workflow_details(workflow_id):
    wf = load_workflow(workflow_id)
    if wf:
        return jsonify(asdict(wf))
    return jsonify({"error": "Workflow not found"}), 404

@app.route('/api/suggest-next-steps/<case_id>', methods=['GET'])
def suggest_next_steps_route(case_id):
    case = load_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    workflow_def = load_workflow(case.workflow_id)
    if not workflow_def:
        return jsonify({"error": "Workflow definition not found"}), 404
    prompt_suggest_steps = load_prompt("suggest_next_steps")
    if prompt_suggest_steps:
        suggestions = suggest_next_steps_with_gemini(case, workflow_def, prompt_suggest_steps)
        return jsonify(suggestions)
    else:
        return jsonify({"error": "Prompt 'suggest_next_steps' not found"}), 500

@app.route('/api/suggest-section/<case_id>', methods=['POST'])
def suggest_section_route(case_id):
    data = request.get_json()
    xml_summary = data.get('xml_summary')
    goal = data.get('goal')
    intended_conclusion = data.get('intended_conclusion')
    if not xml_summary or not goal or not intended_conclusion:
        return jsonify({"error": "Missing one or more required parameters: xml_summary, goal, intended_conclusion"}), 400
    case = load_case(case_id)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    workflow_def = load_workflow(case.workflow_id)
    if not workflow_def:
        return jsonify({"error": "Workflow definition not found"}), 404
    prompt_suggest_section = load_prompt("suggest_section")
    if not prompt_suggest_section:
        return jsonify({"error": "Prompt 'suggest_section' not found"}), 500
    suggestion_xml = suggest_section_with_gemini(case, xml_summary, goal, intended_conclusion, prompt_suggest_section)
    return Response(suggestion_xml, mimetype='application/xml')

@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    tasks = task_queue.list_tasks()
    tasks_data = [asdict(task) for task in tasks]
    return jsonify(tasks_data)

@app.route('/api/tasks', methods=['POST'])
def create_task():
    data = request.get_json()
    task_type = data.get("type")
    parameters = data.get("parameters", {})
    priority = int(data.get("priority", 0))
    speed = float(data.get("speed", 1.0))
    task = Task(priority=priority, type=task_type, parameters=parameters, speed=speed)
    tasks_dict[task.id] = task
    task_queue.add_task(task)
    return jsonify({"message": "Task created", "task_id": task.id}), 201

@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    task = tasks_dict.get(task_id)
    if task:
        return jsonify(asdict(task))
    return jsonify({"error": "Task not found"}), 404

# ---------------------------
# Main: Run the Flask App
# ---------------------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
