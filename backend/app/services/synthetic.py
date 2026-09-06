"""Synthetic mailbox + PDF fixtures. Made-up patients only — never real data."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.mail import send_mail
from app.services.pdf_build import (
    build_article_pdf,
    build_handwritten_pdf,
    build_scanned_pdf,
    build_simple_pdf,
)

DISCLAIMER = (
    "This is synthetic mailbox data for the Clinevo reviewer prototype. "
    "No real patient, reporter, or product complaint is described.\n\n"
)

TAG_ICSR = "icsr"
TAG_PQC = "pqc"
TAG_MI = "mi"
TAG_IRRELEVANT = "irrelevant"
TAG_DIGITAL = "digital"
TAG_SCANNED = "scanned"
TAG_HANDWRITTEN = "handwritten"
TAG_ARTICLE = "article"
TAG_NON_ENGLISH = "non_english"
TAG_BATCH = "batch"


@dataclass(frozen=True)
class SyntheticEmail:
    key: str
    subject: str
    text_body: str
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)
    tags: frozenset[str] = field(default_factory=frozenset)
    sender_name: str = "Fictional Reporter"


def _pdf(name: str, data: bytes) -> tuple[str, str, bytes]:
    return (name, "application/pdf", data)


def _icsr_digital(filename: str, title: str, lines: list[str]) -> tuple[str, str, bytes]:
    return _pdf(filename, build_simple_pdf(title, lines))


def synthetic_catalog() -> list[SyntheticEmail]:
    rash_pdf = _icsr_digital(
        "fictional-rash-note.pdf",
        "Fictional clinic note — Examplemab rash",
        [
            "Patient: Alex Rivera (made-up). Age: 54 years. Sex: female.",
            "Product: Clinevo Examplemab 40 mg, subcutaneous, started 12 Mar 2024.",
            "Event: widespread rash two days after the third dose.",
            "Outcome: recovering after topical steroid. Reporter: nurse Jordan Lee, Canada.",
        ],
    )
    anaphylaxis_pdf = _icsr_digital(
        "fictional-anaphylaxis-note.pdf",
        "Fictional ER note — Examplemab anaphylaxis",
        [
            "Patient: Morgan Chen (made-up). Age: 29 years. Sex: male. Weight: 81 kg.",
            "Product: Examplemab 40 mg subcutaneous, first dose today.",
            "Event: throat tightness, hives, and hypotension 20 minutes after injection.",
            "Treated with epinephrine. Outcome: recovered. Country: United States.",
        ],
    )
    hospital_pdf = _icsr_digital(
        "fictional-hospital-note.pdf",
        "Fictional discharge summary — Exampletab hepatitis",
        [
            "Patient: Riley Patel (made-up), 61-year-old male, history of hypertension.",
            "Product: Exampletab 10 mg oral daily from 02 Jan 2024 to 18 Feb 2024.",
            "Event: jaundice and ALT 640. Hospitalized for 4 days. Not life-threatening.",
            "Outcome: recovering. Reporter: Dr. Sam Ortiz, Spain. Height: not recorded.",
        ],
    )
    fatal_pdf = _icsr_digital(
        "fictional-thin-case.pdf",
        "Fictional sparse death report",
        [
            "A made-up caller said a relative died after taking Examplemab.",
            "Age, sex, dose, dates, and medical history were not provided.",
            "Do not invent missing facts. Outcome stated as death only.",
        ],
    )
    dual_pdf = _icsr_digital(
        "fictional-vial-and-rash.pdf",
        "Fictional note — cracked vial plus rash",
        [
            "Patient: Casey Nguyen (made-up), 47-year-old female.",
            "Product: Examplemab lot EX-2209. The vial arrived with a cracked neck.",
            "She still injected the remaining liquid and developed a fever and rash the next day.",
            "Outcome: recovering. Photo of the vial was mentioned but not attached.",
        ],
    )
    scanned_pdf = build_scanned_pdf(
        "Fictional scanned ER card",
        [
            "SYNTHETIC SCAN — image only, no digital text layer.",
            "Patient: Quinn Adler (made-up) 72 F",
            "Drug: Exampletab 10 mg oral",
            "Reaction: sudden dizziness and fall after first tablet",
            "Outcome: hospitalized overnight, recovering",
            "Reporter: paramedic, Ireland",
        ],
    )
    handwritten_pdf = build_handwritten_pdf(
        "Fictional handwritten card",
        [
            "Made-up handwriting sample",
            "Name: Taylor Brooks age 8 (fictional child)",
            "Sex: male  Weight: 26 kg",
            "Product: Examplemab 20 mg SC",
            "Event: vomiting twice the night after dose 2",
            "Outcome: recovered  Reporter: parent, UK",
        ],
    )
    spanish_pdf = _icsr_digital(
        "nota-ficticia-es.pdf",
        "Nota clinica ficticia (espanol)",
        [
            "Paciente: Lucia Mora (inventada), 45 anos, sexo femenino.",
            "Producto: Examplemab 40 mg subcutaneo.",
            "Acontecimiento: erupcion generalizada al segundo dia de la tercera dosis.",
            "Desenlace: en recuperacion. Pais: Mexico. Esto es un documento sintetico.",
        ],
    )
    french_pdf = _icsr_digital(
        "note-fictive-fr.pdf",
        "Note clinique fictive (francais)",
        [
            "Patient: Hugo Martin (invente), 38 ans, sexe masculin.",
            "Produit: Exampletab 10 mg voie orale.",
            "Evenement: dyspnee et toux deux heures apres la prise.",
            "Evolution: retabli. Pays: France. Document synthetique uniquement.",
        ],
    )
    pqc_seal_pdf = _icsr_digital(
        "fictional-broken-seal.pdf",
        "Fictional warehouse quality note",
        [
            "Product: Exampletab 10 mg bottles. Lot EX-4401.",
            "Issue: torn induction seal and cracked cap on arrival. No patient involved.",
            "A photo of the cap was taken. This is a product quality complaint only.",
        ],
    )
    pqc_color_pdf = _icsr_digital(
        "fictional-wrong-color.pdf",
        "Fictional packing complaint",
        [
            "Product: Examplemab 40 mg prefilled syringe. Lot EX-1188.",
            "Issue: solution looks brown instead of colorless. Possible contamination.",
            "No injection was given. No adverse event. Counterfeit is not alleged.",
        ],
    )
    article_one = _pdf(
        "fictional-article-single-case.pdf",
        build_article_pdf(
            "Fictional case of rash after Examplemab",
            "A. Rivera (invented); J. Lee, RN (invented)",
            "We describe one made-up adult who developed a rash after Examplemab. "
            "This article is synthetic sample data for software testing.",
            [
                "Introduction. Examplemab is a fictional monoclonal antibody used only in this prototype. "
                "Published safety data do not exist because the product is invented.",
                "Case. A 54-year-old woman (initials A.R., made-up) received Examplemab 40 mg subcutaneous. "
                "Two days after the third dose she developed a widespread rash and low-grade fever. "
                "She was seen in clinic, treated with a topical steroid, and is recovering.",
                "No hospitalization occurred. Past history was not stated in this fictional note.",
            ],
            [
                "Discussion. A single invented case cannot estimate risk. "
                "The temporal association is the only reason this narrative resembles an ICSR.",
                "We did not collect weight, height, or batch number. Those fields must remain unknown.",
                "Conclusion. Software reviewers should extract only facts written here and leave the rest Not stated.",
            ],
            ["Rivera A. Fictional Pharmacovigilance Lett. 2024;12:1-2."],
        ),
    )
    article_two = _pdf(
        "fictional-article-two-cases.pdf",
        build_article_pdf(
            "Two fictional Examplemab cases in one letter",
            "S. Ortega; K. Nair (invented authors)",
            "Two distinct made-up patients are reported so the literature splitter can separate them.",
            [
                "Case 1. Jordan Hale, a 33-year-old man (fictional), received Examplemab 40 mg. "
                "He developed hives and lip swelling 15 minutes after the first injection. "
                "Epinephrine was given. Outcome: recovered. Country: Australia.",
                "He had no listed medical history. Dose start date was 04 May 2024. Stop date was the same day.",
            ],
            [
                "Case 2. Priya Shah, a 70-year-old woman (fictional), took Exampletab 10 mg daily. "
                "After two weeks she noticed yellow skin and dark urine. She was hospitalized. "
                "ALT was 510. Outcome: recovering. Reporter role: physician. Country: India.",
                "These two people must not be merged. Each is a separate identifiable patient case.",
            ],
            ["Ortega S. Fictional Pharmacovigilance Lett. 2024;12:3-4."],
        ),
    )
    article_none = _pdf(
        "fictional-article-methods-only.pdf",
        build_article_pdf(
            "Fictional methods paper on mailbox classification",
            "Clinevo Prototype Lab (invented)",
            "This paper explains a toy algorithm. It contains no patient narrative.",
            [
                "Background. Automated inbox tools need labeled examples. All examples in this journal issue are invented.",
                "Methods. We counted tokens in synthetic emails. No human subjects were enrolled. "
                "No medicinal product was administered to a person.",
                "There is no adverse event, no quality defect, and no identifiable patient.",
            ],
            [
                "Results. Accuracy numbers in this paper are made up (0.00). They must not be treated as evidence.",
                "Discussion. Literature screening should mark this document as not an identifiable patient case.",
                "Funding. None. Conflicts: none. This PDF exists only to test the negative path.",
            ],
            ["Prototype Lab. Fictional Methods. 2024;1:1."],
        ),
    )
    article_peds = _pdf(
        "fictional-article-pediatric.pdf",
        build_article_pdf(
            "Fictional pediatric vomiting after Examplemab",
            "L. Brooks (invented caregiver report, written up by a fictional clinician)",
            "One made-up child is described. Age is 8 years.",
            [
                "Case. An 8-year-old boy (Taylor Brooks, fictional) received Examplemab 20 mg subcutaneous. "
                "The night after the second dose he vomited twice and felt tired. "
                "He recovered the next morning without hospital care. Weight 26 kg. Country: United Kingdom.",
                "No quality complaint is described. The product packaging was intact.",
            ],
            [
                "Discussion. Pediatric fictional cases still need the same extraction fields. "
                "Height was not recorded. Start date was not stated.",
                "Reviewers should refuse to invent dates or seriousness beyond what is written.",
            ],
            ["Brooks L. Fictional Pediatr Lett. 2024;2:9."],
        ),
    )
    article_three = _pdf(
        "fictional-article-case-series.pdf",
        build_article_pdf(
            "Fictional three-patient Exampletab series",
            "M. Okonkwo; R. Singh (invented)",
            "Three separate made-up people, each with a different reaction to Exampletab.",
            [
                "Case A. A 22-year-old woman developed headache one hour after Exampletab 10 mg. Recovered.",
                "Case B. A 55-year-old man developed a swollen tongue after Exampletab and was treated in clinic. Recovered.",
                "Case C. An 81-year-old woman fell after dizziness attributed to Exampletab and stayed overnight in hospital.",
            ],
            [
                "None of these names were collected. Sex and age are the only identifiers given.",
                "Lot numbers were not stated. Photos were not mentioned.",
                "The splitter should emit three cases, not one blended narrative.",
            ],
            ["Okonkwo M. Fictional Series. 2024;4:12-13."],
        ),
    )

    return [
        SyntheticEmail(
            key="icsr-rash-clinic",
            subject="[SYNTHETIC] Possible rash after Examplemab — fictional clinic case",
            text_body=(
                DISCLAIMER
                + "Reporter (fictional nurse Jordan Lee, Canada) says a 54-year-old woman developed a rash "
                "and fever after Examplemab 40 mg subcutaneous. She was seen in clinic and is recovering. "
                "A made-up clinic note is attached.\n"
            ),
            attachments=[rash_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-anaphylaxis",
            subject="[SYNTHETIC] Anaphylaxis after first Examplemab — fictional ER case",
            text_body=(
                DISCLAIMER
                + "Fictional ER report: Morgan Chen, 29-year-old man, 81 kg, throat tightness and hives "
                "20 minutes after the first Examplemab 40 mg injection. Epinephrine given. Recovered. "
                "United States. Attached note repeats the same invented facts.\n"
            ),
            attachments=[anaphylaxis_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-hepatitis-body",
            subject="[SYNTHETIC] Jaundice while on Exampletab — fictional, no PDF",
            text_body=(
                DISCLAIMER
                + "Phone intake (synthetic): Riley Patel, 61-year-old man with hypertension, took "
                "Exampletab 10 mg oral daily from 2 Jan 2024 until 18 Feb 2024. He developed jaundice "
                "and was hospitalized 4 days. ALT 640. Recovering. Reporter Dr. Sam Ortiz, Spain. "
                "Height was not given. No attachment.\n"
            ),
            attachments=[],
            tags=frozenset({TAG_ICSR, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-hospital-lt",
            subject="[SYNTHETIC] Hospitalization after Exampletab — fictional discharge note",
            text_body=(
                DISCLAIMER
                + "Please review the attached fictional discharge summary. Same case as the phone intake "
                "but the PDF is the source of record for page citations.\n"
            ),
            attachments=[hospital_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-scanned-er",
            subject="[SYNTHETIC] Scanned ER card — fictional dizziness after Exampletab",
            text_body=(
                DISCLAIMER
                + "Attached is a made-up scanned card (image-only PDF) for Quinn Adler, 72 F, dizziness "
                "and fall after the first Exampletab tablet. Hospitalized overnight. Recovering. Ireland.\n"
            ),
            attachments=[_pdf("fictional-scanned-er-card.pdf", scanned_pdf)],
            tags=frozenset({TAG_ICSR, TAG_SCANNED, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-handwritten-card",
            subject="[SYNTHETIC] Handwritten pediatric card — fictional vomiting",
            text_body=(
                DISCLAIMER
                + "Parent (fictional, UK) mailed a handwritten card: Taylor Brooks, 8-year-old boy, 26 kg, "
                "vomited twice the night after Examplemab 20 mg dose 2. Recovered. Please OCR the scan.\n"
            ),
            attachments=[_pdf("fictional-handwritten-card.pdf", handwritten_pdf)],
            tags=frozenset({TAG_ICSR, TAG_HANDWRITTEN, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-spanish-rash",
            subject="[SYNTHETIC] Erupcion tras Examplemab — caso ficticio en espanol",
            text_body=(
                DISCLAIMER
                + "Correo sintetico en espanol: Lucia Mora, 45 anos, sexo femenino, erupcion generalizada "
                "al segundo dia de la tercera dosis de Examplemab 40 mg. En recuperacion. Mexico. "
                "La nota adjunta esta en espanol y debe traducirse sin perder el original.\n"
            ),
            attachments=[spanish_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_NON_ENGLISH, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-french-dyspnea",
            subject="[SYNTHETIC] Dyspnee apres Exampletab — cas fictif en francais",
            text_body=(
                DISCLAIMER
                + "Message synthetique en francais: Hugo Martin, 38 ans, homme, dyspnee et toux deux heures "
                "apres Exampletab 10 mg. Retabli. France. PDF francais en piece jointe.\n"
            ),
            attachments=[french_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_NON_ENGLISH, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-fatal-thin",
            subject="[SYNTHETIC] Relative died after Examplemab — sparse fictional report",
            text_body=(
                DISCLAIMER
                + "A made-up caller said a relative died after taking Examplemab. Age, sex, dose, dates, "
                "and history were not provided. Do not invent them. Attached PDF is equally thin.\n"
            ),
            attachments=[fatal_pdf],
            tags=frozenset({TAG_ICSR, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="icsr-dual-defect",
            subject="[SYNTHETIC] Cracked vial and then a rash — fictional dual-label case",
            text_body=(
                DISCLAIMER
                + "Casey Nguyen, 47-year-old woman, received Examplemab lot EX-2209 from a vial with a "
                "cracked neck, then developed fever and rash. Photo of the vial was mentioned. "
                "This should classify as both a safety report and a quality complaint.\n"
            ),
            attachments=[dual_pdf],
            tags=frozenset({TAG_ICSR, TAG_PQC, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="article-case-one",
            subject="[SYNTHETIC] Fictional journal letter — one Examplemab rash case",
            text_body=(
                DISCLAIMER
                + "Sharing a made-up open-access letter for literature screening. One identifiable "
                "fictional patient is described in the two-column PDF.\n"
            ),
            attachments=[article_one],
            tags=frozenset({TAG_ICSR, TAG_ARTICLE, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="article-two-cases",
            subject="[SYNTHETIC] Fictional letter with two distinct patient cases",
            text_body=(
                DISCLAIMER
                + "Literature sample with TWO fictional patients (Jordan Hale anaphylaxis; Priya Shah "
                "hepatitis). Use upload-or-split to emit two reviewer cases.\n"
            ),
            attachments=[article_two],
            tags=frozenset({TAG_ICSR, TAG_ARTICLE, TAG_DIGITAL}),
        ),
        SyntheticEmail(
            key="article-no-patient",
            subject="[SYNTHETIC] Fictional methods paper — no patient case",
            text_body=(
                DISCLAIMER
                + "Methods-only toy paper. Literature screening should answer no identifiable patient case.\n"
            ),
            attachments=[article_none],
            tags=frozenset({TAG_IRRELEVANT, TAG_ARTICLE, TAG_DIGITAL}),
        ),
        SyntheticEmail(
            key="article-pediatric",
            subject="[SYNTHETIC] Fictional pediatric letter — vomiting after Examplemab",
            text_body=(
                DISCLAIMER
                + "One fictional child (age 8) is described in the attached two-column article.\n"
            ),
            attachments=[article_peds],
            tags=frozenset({TAG_ICSR, TAG_ARTICLE, TAG_DIGITAL}),
        ),
        SyntheticEmail(
            key="article-series-three",
            subject="[SYNTHETIC] Fictional three-patient Exampletab series",
            text_body=(
                DISCLAIMER
                + "Case series with three unnamed but age/sex-identified fictional people. Split should "
                "create three cases.\n"
            ),
            attachments=[article_three],
            tags=frozenset({TAG_ICSR, TAG_ARTICLE, TAG_DIGITAL}),
        ),
        SyntheticEmail(
            key="pqc-broken-seal",
            subject="[SYNTHETIC] Bottle arrived with a broken seal — fictional product complaint",
            text_body=(
                DISCLAIMER
                + "Warehouse note (synthetic): Exampletab 10 mg bottle lot EX-4401 arrived with a torn "
                "seal and cracked cap. Photo taken. No patient was involved. Quality complaint only.\n"
            ),
            attachments=[pqc_seal_pdf],
            tags=frozenset({TAG_PQC, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="pqc-wrong-color",
            subject="[SYNTHETIC] Syringe liquid is brown — fictional quality complaint",
            text_body=(
                DISCLAIMER
                + "Pharmacist (synthetic): Examplemab 40 mg lot EX-1188 looks brown, not colorless. "
                "Not injected. No adverse event. Asking for a replacement. PQC only.\n"
            ),
            attachments=[pqc_color_pdf],
            tags=frozenset({TAG_PQC, TAG_DIGITAL, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="mi-with-food",
            subject="[SYNTHETIC] Can Exampletab be taken with breakfast? — fictional MI",
            text_body=(
                DISCLAIMER
                + "Hello medical information (synthetic request),\n\n"
                "Can Exampletab 10 mg be taken with breakfast, and is there an interaction with omeprazole?\n"
                "No adverse event and no product defect is being reported.\n"
            ),
            attachments=[],
            tags=frozenset({TAG_MI, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="mi-storage",
            subject="[SYNTHETIC] How to store Examplemab syringes — fictional MI",
            text_body=(
                DISCLAIMER
                + "Synthetic MI only: does Examplemab 40 mg need refrigeration after opening the carton? "
                "Can it go through airport security? No reaction, no damaged product.\n"
            ),
            attachments=[],
            tags=frozenset({TAG_MI}),
        ),
        SyntheticEmail(
            key="marketing-mixer",
            subject="[SYNTHETIC] Industry conference invitation — not a case",
            text_body=(
                "Join the fictional Clinevo summer science mixer. This is marketing mail and should "
                "classify as not relevant. No patient, product quality issue, or medical question is included.\n"
            ),
            attachments=[],
            tags=frozenset({TAG_IRRELEVANT, TAG_BATCH}),
        ),
        SyntheticEmail(
            key="pqc-csv-nonpdf",
            subject="[SYNTHETIC] Packing list CSV with broken seal — fictional, non-PDF",
            text_body=(
                DISCLAIMER
                + "Same broken-seal story as the quality complaint, but the attachment is a CSV so intake "
                "can log a non-PDF and skip it.\n"
            ),
            attachments=[
                (
                    "packing-list.csv",
                    "text/csv",
                    b"lot,issue,fictional\nEX-4401,broken seal,yes\n",
                )
            ],
            tags=frozenset({TAG_PQC}),
        ),
    ]


def catalog_by_key() -> dict[str, SyntheticEmail]:
    return {item.key: item for item in synthetic_catalog()}


def batch_keys() -> list[str]:
    return [item.key for item in synthetic_catalog() if TAG_BATCH in item.tags]


def article_upload_keys() -> list[str]:
    return [item.key for item in synthetic_catalog() if TAG_ARTICLE in item.tags]


def _count_pdfs(items: list[SyntheticEmail], tag: str) -> int:
    total = 0
    for item in items:
        if tag not in item.tags:
            continue
        total += sum(1 for name, mime, _ in item.attachments if name.lower().endswith(".pdf") or "pdf" in mime)
    return total


def catalog_coverage(items: list[SyntheticEmail] | None = None) -> dict[str, int]:
    items = items if items is not None else synthetic_catalog()
    icsr_emails = sum(1 for item in items if TAG_ICSR in item.tags)
    return {
        "emails_with_reaction": icsr_emails,
        "digital_pdfs": _count_pdfs(items, TAG_DIGITAL),
        "scanned_or_handwritten_pdfs": _count_pdfs(items, TAG_SCANNED) + _count_pdfs(items, TAG_HANDWRITTEN),
        "article_pdfs": _count_pdfs(items, TAG_ARTICLE),
        "non_english_pdfs": _count_pdfs(items, TAG_NON_ENGLISH),
        "pqc_only": sum(1 for item in items if TAG_PQC in item.tags and TAG_ICSR not in item.tags),
        "mi_only": sum(1 for item in items if TAG_MI in item.tags and TAG_ICSR not in item.tags and TAG_PQC not in item.tags),
        "irrelevant": sum(1 for item in items if TAG_IRRELEVANT in item.tags and TAG_ICSR not in item.tags),
        "catalog_size": len(items),
        "batch_size": sum(1 for item in items if TAG_BATCH in item.tags),
    }


def required_coverage_ok(coverage: dict[str, int] | None = None) -> bool:
    got = coverage or catalog_coverage()
    return (
        got["emails_with_reaction"] >= 10
        and got["digital_pdfs"] >= 5
        and got["scanned_or_handwritten_pdfs"] >= 2
        and got["article_pdfs"] >= 5
        and got["non_english_pdfs"] >= 2
        and got["pqc_only"] >= 2
        and got["mi_only"] >= 2
        and got["irrelevant"] >= 1
    )


def send_synthetic_mailbox(to_email: str, keys: list[str] | None = None) -> dict:
    catalog = catalog_by_key()
    selected_keys = keys or [item.key for item in synthetic_catalog()]
    sent: list[str] = []
    for key in selected_keys:
        item = catalog[key]
        send_mail(
            to_email,
            item.subject,
            item.text_body,
            attachments=item.attachments,
        )
        sent.append(item.key)
    return {"to": to_email, "sent": sent, "count": len(sent)}
