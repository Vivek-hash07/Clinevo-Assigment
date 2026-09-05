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
