from flask import Flask, request, jsonify, Response
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List
import json
import os
import uuid

# --- Data Models ---
@dataclass
class Document:
    id: str
    type: str
    upload_date: datetime
    content: str
    analysis: dict
    stage: str

@dataclass
class Case:
    id: str
    current_stage: str
    documents: List[Document]
    timeline: List[dict]
    status: str

# --- JSON Storage Helpers ---
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    else:
        return {"cases": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def document_to_dict(doc: Document) -> dict:
    doc_dict = asdict(doc)
    # Convert datetime to ISO string for JSON storage
    doc_dict["upload_date"] = doc.upload_date.isoformat()
    return doc_dict

def case_to_dict(case: Case) -> dict:
    return {
        "id": case.id,
        "current_stage": case.current_stage,
        "documents": [document_to_dict(doc) for doc in case.documents],
        "timeline": case.timeline,
        "status": case.status
    }

def case_from_dict(data: dict) -> Case:
    documents = [
        Document(
            id=doc["id"],
            type=doc["type"],
            upload_date=datetime.fromisoformat(doc["upload_date"]),
            content=doc["content"],
            analysis=doc["analysis"],
            stage=doc["stage"]
        )
        for doc in data.get("documents", [])
    ]
    return Case(
        id=data["id"],
        current_stage=data["current_stage"],
        documents=documents,
        timeline=data.get("timeline", []),
        status=data["status"]
    )

def get_case(case_id: str) -> Case:
    data = load_data()
    if case_id in data["cases"]:
        return case_from_dict(data["cases"][case_id])
    else:
        # Create a new case if it doesn't exist
        new_case = Case(id=case_id, current_stage="notice", documents=[], timeline=[], status="active")
        data["cases"][case_id] = case_to_dict(new_case)
        save_data(data)
        return new_case

def update_case_documents(case_id: str, doc: Document):
    data = load_data()
    if case_id not in data["cases"]:
        new_case = Case(id=case_id, current_stage="notice", documents=[], timeline=[], status="active")
        data["cases"][case_id] = case_to_dict(new_case)
    case_data = data["cases"][case_id]
    case_data["documents"].append(document_to_dict(doc))
    # Optionally update timeline with an event log
    case_data.setdefault("timeline", []).append({
        "timestamp": datetime.now().isoformat(),
        "event": f"Document {doc.id} uploaded"
    })
    save_data(data)

def generate_id() -> str:
    return str(uuid.uuid4())

def get_missing_requirements(case: Case, proposed_stage: str) -> List[str]:
    current_stage = case.current_stage
    stage_info = workflow.stages.get(current_stage)
    if not stage_info or proposed_stage not in stage_info["next_stages"]:
        return ["Invalid stage transition"]
    required_docs = stage_info["required_docs"]
    missing = []
    for req in required_docs:
        if not any(doc.type == req for doc in case.documents):
            missing.append(req)
    return missing

# --- Workflow Class ---
class EvictionWorkflow:
    def __init__(self):
        self.stages = {
            "notice": {
                "required_docs": ["notice_to_cure", "proof_of_service"],
                "next_stages": ["resolved", "complaint_filed"],
                "waiting_period": 3  # days
            },
            "complaint_filed": {
                "required_docs": ["summons", "complaint", "proof_of_service"],
                "next_stages": ["default", "answer_filed", "motion_filed"],
                "waiting_period": 10
            },
            # Add more stages as needed
        }
        
    def validate_stage_transition(self, case: Case, new_stage: str) -> bool:
        current_stage = case.current_stage
        stage_info = self.stages.get(current_stage)
        if stage_info and new_stage in stage_info["next_stages"]:
            required_docs = stage_info["required_docs"]
            return all(any(doc.type == req for doc in case.documents) for req in required_docs)
        return False

# --- Flask App ---
app = Flask(__name__)
workflow = EvictionWorkflow()

# Endpoint to serve the React frontend
@app.route('/')
def index():
    html_content = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Eviction Workflow System</title>
    <!-- Load React and Babel from CDN for demo purposes -->
    <script src="https://unpkg.com/react@17/umd/react.development.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@17/umd/react-dom.development.js" crossorigin></script>
    <script src="https://unpkg.com/babel-standalone@6.26.0/babel.min.js"></script>
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; }
      input { margin: 5px; padding: 5px; }
      button { margin: 5px; padding: 5px 10px; }
      pre { background: #f0f0f0; padding: 10px; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="text/babel">
      function App() {
        const [caseId, setCaseId] = React.useState('');
        const [documentType, setDocumentType] = React.useState('');
        const [file, setFile] = React.useState(null);
        const [uploadResponse, setUploadResponse] = React.useState(null);
        const [newStage, setNewStage] = React.useState('');
        const [transitionResponse, setTransitionResponse] = React.useState(null);

        const handleFileChange = (e) => {
          setFile(e.target.files[0]);
        };

        const handleUpload = async () => {
          if (!file || !caseId || !documentType) {
            alert("Please provide all required fields.");
            return;
          }
          const formData = new FormData();
          formData.append('file', file);
          formData.append('case_id', caseId);
          formData.append('document_type', documentType);
          
          try {
            const res = await fetch('/api/upload-document', {
              method: 'POST',
              body: formData
            });
            const data = await res.json();
            setUploadResponse(data);
          } catch (error) {
            console.error(error);
          }
        };

        const handleValidateTransition = async () => {
          if (!caseId || !newStage) {
            alert("Please enter a case ID and a proposed new stage.");
            return;
          }
          try {
            const res = await fetch('/api/validate-transition', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ case_id: caseId, new_stage: newStage })
            });
            const data = await res.json();
            setTransitionResponse(data);
          } catch (error) {
            console.error(error);
          }
        };

        return (
          <div style={{ padding: '2rem' }}>
            <h1>Eviction Workflow System</h1>
            
            <section style={{ marginBottom: '2rem' }}>
              <h2>Upload Document</h2>
              <div>
                <input 
                  type="text" 
                  placeholder="Case ID" 
                  value={caseId} 
                  onChange={(e) => setCaseId(e.target.value)} 
                />
              </div>
              <div>
                <input 
                  type="text" 
                  placeholder="Document Type (e.g., notice_to_cure)" 
                  value={documentType} 
                  onChange={(e) => setDocumentType(e.target.value)} 
                />
              </div>
              <div>
                <input type="file" onChange={handleFileChange} />
              </div>
              <button onClick={handleUpload}>Upload Document</button>
              {uploadResponse && (
                <pre>{JSON.stringify(uploadResponse, null, 2)}</pre>
              )}
            </section>

            <section>
              <h2>Validate Stage Transition</h2>
              <div>
                <input 
                  type="text" 
                  placeholder="Case ID" 
                  value={caseId} 
                  onChange={(e) => setCaseId(e.target.value)} 
                />
              </div>
              <div>
                <input 
                  type="text" 
                  placeholder="Proposed New Stage (e.g., complaint_filed)" 
                  value={newStage} 
                  onChange={(e) => setNewStage(e.target.value)} 
                />
              </div>
              <button onClick={handleValidateTransition}>Validate Transition</button>
              {transitionResponse && (
                <pre>{JSON.stringify(transitionResponse, null, 2)}</pre>
              )}
            </section>
          </div>
        );
      }

      ReactDOM.render(<App />, document.getElementById('root'));
    </script>
  </body>
</html>
    """
    return Response(html_content, mimetype='text/html')

# --- API Endpoints ---
@app.route('/api/upload-document', methods=['POST'])
def upload_document():
    """
    Handle document upload and analysis.
    Expects:
      - A file in the "file" field.
      - Form fields "case_id" and "document_type".
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    case_id = request.form.get('case_id')
    doc_type = request.form.get('document_type')

    if not case_id or not doc_type:
        return jsonify({"error": "Missing case_id or document_type"}), 400

    # Simulate processing the file and calling the Vision API.
    # In production, you would handle file storage and API calls appropriately.
    extracted_text = "Simulated extracted text."
    analysis_result = {}  # Simulated analysis result

    # Get or create the current case
    case = get_case(case_id)

    # Create a new document record
    doc = Document(
        id=generate_id(),
        type=doc_type,
        upload_date=datetime.now(),
        content=extracted_text,
        analysis=analysis_result,
        stage=case.current_stage
    )

    # Update the case with the new document
    update_case_documents(case_id, doc)

    return jsonify({"message": "Document processed", "document_id": doc.id})

@app.route('/api/validate-transition', methods=['POST'])
def validate_transition():
    """
    Validate if a case can transition to the next stage.
    Expects a JSON payload with:
      - case_id
      - new_stage
    """
    data = request.json
    case_id = data.get('case_id')
    proposed_stage = data.get('new_stage')

    if not case_id or not proposed_stage:
        return jsonify({"error": "Missing case_id or new_stage"}), 400

    case = get_case(case_id)
    if workflow.validate_stage_transition(case, proposed_stage):
        return jsonify({
            "valid": True,
            "next_requirements": workflow.stages.get(proposed_stage, {})
        })
    else:
        missing = get_missing_requirements(case, proposed_stage)
        return jsonify({
            "valid": False,
            "missing_requirements": missing
        })

@app.route('/api/case/<case_id>', methods=['GET'])
def get_case_details(case_id):
    case = get_case(case_id)
    return jsonify(case_to_dict(case))

# --- Main ---
if __name__ == '__main__':
    # For demo purposes, run in debug mode.
    app.run(debug=True)
