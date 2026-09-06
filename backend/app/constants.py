QUEUE_STATUSES = ("pending", "processing", "ready", "reviewed")

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_REVIEWED = "reviewed"

PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf"})
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

FLAVOR_DIGITAL = "digital"
FLAVOR_SCANNED = "scanned"
FLAVOR_HANDWRITTEN = "handwritten"
FLAVOR_ARTICLE = "article"
FLAVOR_FORM = "form"
FLAVOR_MIXED = "mixed"
FLAVOR_UNKNOWN = "unknown"
PDF_FLAVORS = frozenset(
    {
        FLAVOR_DIGITAL,
        FLAVOR_SCANNED,
        FLAVOR_HANDWRITTEN,
        FLAVOR_ARTICLE,
        FLAVOR_FORM,
        FLAVOR_MIXED,
        FLAVOR_UNKNOWN,
    }
)

EXTRACT_PDFPLUMBER = "pdfplumber"
EXTRACT_TESSERACT = "tesseract"
EXTRACT_VISION = "vision"
EXTRACT_HYBRID = "hybrid"
EXTRACT_LLM_FALLBACK = "llm_fallback"

PROMPT_PDF_STEP1 = "pdf_step1_v1"
PROMPT_UNDERSTAND = "understand_v1"
PROMPT_CLASSIFY = "classify_v1"
PROMPT_EXTRACT_ICSR = "extract_icsr_v1"
PROMPT_EXTRACT_PQC = "extract_pqc_v1"
PROMPT_EXTRACT_MI = "extract_mi_v1"
PROMPT_LITERATURE = "literature_screen_v1"

SOURCE_GMAIL = "gmail"
SOURCE_UPLOAD = "upload"
SOURCE_SPLIT = "split"
SOURCE_FIXTURE = "fixture"
MESSAGE_SOURCES = (SOURCE_GMAIL, SOURCE_UPLOAD, SOURCE_SPLIT, SOURCE_FIXTURE)

CAT_ICSR = "Safety Report (ICSR)"
CAT_PQC = "Quality Complaint (PQC)"
CAT_MI = "Info Request (MI)"
CAT_IRRELEVANT = "Not Relevant"
MESSAGE_CATEGORIES = (CAT_ICSR, CAT_PQC, CAT_MI, CAT_IRRELEVANT)

NOT_STATED = "Not stated"

ICSR_FIELDS = (
    "patient.age",
    "patient.sex",
    "patient.weight",
    "patient.height",
    "patient.history",
    "reporter.name",
    "reporter.role",
    "reporter.country",
    "product.name",
    "product.dose",
    "product.route",
    "product.start_date",
    "product.stop_date",
    "reaction.description",
    "reaction.onset",
    "reaction.outcome",
    "severity.seriousness",
    "narrative.summary",
)
PQC_FIELDS = (
    "pqc.product",
    "pqc.batch_lot",
    "pqc.defect",
    "pqc.photo_mentioned",
)
MI_FIELDS = (
    "mi.questions",
    "mi.product",
    "mi.topic",
)
DERIVED_FIELDS = frozenset({"narrative.summary"})
REVIEW_ACTION_ACCEPT = "accept"
REVIEW_ACTION_OVERRIDE = "override"
REVIEW_ACTION_COMPLETE = "complete"
REVIEW_LOCK_ACTIONS = frozenset({REVIEW_ACTION_ACCEPT, REVIEW_ACTION_OVERRIDE})
OVERRIDE_REASON_MIN_CHARS = 8
REVIEW_VALUE_MAX_CHARS = 8000
REVIEW_REASON_MAX_CHARS = 2000

FIELD_GROUPS = (
    ("icsr", CAT_ICSR, ICSR_FIELDS),
    ("pqc", CAT_PQC, PQC_FIELDS),
    ("mi", CAT_MI, MI_FIELDS),
)

FIELD_LABELS = {
    "patient.age": "Patient age",
    "patient.sex": "Patient sex",
    "patient.weight": "Patient weight",
    "patient.height": "Patient height",
    "patient.history": "Relevant history",
    "reporter.name": "Reporter",
    "reporter.role": "Reporter role",
    "reporter.country": "Reporter country",
    "product.name": "Product",
    "product.dose": "Dose",
    "product.route": "Route",
    "product.start_date": "Start date",
    "product.stop_date": "Stop date",
    "reaction.description": "Reaction",
    "reaction.onset": "Onset",
    "reaction.outcome": "Outcome",
    "severity.seriousness": "Seriousness",
    "narrative.summary": "Case narrative",
    "pqc.product": "Product",
    "pqc.batch_lot": "Batch / lot",
    "pqc.defect": "Defect",
    "pqc.photo_mentioned": "Photo mentioned",
    "mi.questions": "Question(s)",
    "mi.product": "Product",
    "mi.topic": "Topic",
}
