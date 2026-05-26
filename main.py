import json
import re
import os
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from mistralai import Mistral
from fpdf import FPDF

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

# ─── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="Calistheni API",
    description="Agent IA Calisthenics — génération de programmes personnalisés",
    version="1.0.0",
)

# ─── CORS ───────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://calistheni.com",
        "https://www.calistheni.com",
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:5500",  # Live Server VS Code
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Mistral client ─────────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY manquante dans les variables d'environnement")

mistral = Mistral(api_key=MISTRAL_API_KEY)
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

# ─── Schémas Pydantic ───────────────────────────────────────────
SKILLS_VALIDES = {
    "Front Lever", "Back Lever", "Planche", "Human Flag",
    "Muscle-Up", "Handstand", "Dragon Flag", "One Arm Pull-Up",
}

class FormData(BaseModel):
    skill_cible: str
    prerequis: dict = {}
    frequence_semaine: int
    duree_seance_min: int
    materiel: list[str]


# ─── Builder de prompt ───────────────────────────────────────────
LABELS_PREREQ = {"oui": "maîtrisé ✓", "en_cours": "en progression →", "non": "pas encore ✗"}

CONSEILS_PAR_SKILL = {
    "Front Lever": "Insiste sur la rétraction et dépression scapulaire. Progresse tuck → advanced tuck → one leg → straddle → full.",
    "Back Lever": "Commence toujours par skin the cat pour la mobilité. Priorité : tenir chaque progression 10 sec avant d'avancer.",
    "Planche": "La progression est lente (6–18 mois). Pseudo planche push-ups et lean quotidiens. Protège les poignets.",
    "Human Flag": "Travail bilatéral indispensable. Alterne côté fort/faible. Push-pull isométrique contre la barre.",
    "Muscle-Up": "L'explosivité et le false grip sont les deux clés. Ne saute pas l'étape du kipping pour apprendre la mécanique.",
    "Handstand": "Travail mur d'abord (dos), puis chest-to-wall, puis free. Travail de poignets quotidien obligatoire.",
    "Dragon Flag": "Hollow body est le fondement absolu. Progresser : tuck → single leg → straddle → full.",
    "One Arm Pull-Up": "Archer pull-ups et tractions lestées (+20–30kg) avant tout. Progression très lente, 6–12 mois minimum.",
}


def build_prompt(data: FormData) -> str:
    # Formatage prérequis
    if data.prerequis:
        prereq_lines = "\n".join(
            f"  - {k}: {LABELS_PREREQ.get(v, v)}"
            for k, v in data.prerequis.items()
        )
    else:
        prereq_lines = "  (non renseignés — suppose un niveau débutant intermédiaire)"

    # Conseils spécifiques au skill
    conseil_skill = CONSEILS_PAR_SKILL.get(data.skill_cible, "")

    # Calcul volume indicatif
    volume_note = (
        "Programme léger" if data.frequence_semaine <= 2
        else "Volume modéré" if data.frequence_semaine <= 4
        else "Volume élevé — prévoir récupération active"
    )

    return f"""Tu es Tarik, coach calisthenics expert avec 10 ans d'expérience.
Tu dois générer un programme de progression ultra-personnalisé pour un athlète.

═══ PROFIL ATHLÈTE ═══
Skill cible        : {data.skill_cible}
Fréquence          : {data.frequence_semaine} séances/semaine ({volume_note})
Durée par séance   : {data.duree_seance_min} minutes
Matériel disponible: {', '.join(data.materiel)}

═══ ÉVALUATION PRÉREQUIS ═══
{prereq_lines}

═══ DIRECTIVES COACH ═══
{conseil_skill}

═══ RÈGLES DU PROGRAMME ═══
1. Génère exactement 1 semaine de programme
2. Chaque semaine a exactement {data.frequence_semaine} séances
3. Adapte les exercices STRICTEMENT au matériel disponible
4. Respecte le volume cohérent avec {data.duree_seance_min} min/séance
5. La progression doit être réaliste semaine par semaine (volume ou intensité +5-10%)
6. Chaque conseil doit être CONCRET et TECHNIQUE (pas générique)
7. Utilise "duree_sec" pour les isométriques/holds, "reps" pour le dynamique (l'autre vaut null)
8. Les jours de repos : nomme-les "Repos actif" ou répartis intelligemment

═══ FORMAT DE RÉPONSE ═══
Réponds UNIQUEMENT avec le JSON ci-dessous, rien d'autre, aucun texte avant ou après.

```json
{{
  "skill_target": "{data.skill_cible}",
  "niveau_actuel": "description précise du niveau actuel basée sur les prérequis évalués",
  "duree_programme_semaines": 4,
  "programme": [
    {{
      "semaine": 1,
      "objectif": "Objectif spécifique et mesurable de cette semaine",
      "charge": "légère | modérée | élevée",
      "seances": [
        {{
          "jour": "Lundi",
          "focus": "Thème de la séance (ex: Force scapulaire, Technique tuck FL...)",
          "duree_estimee_min": {data.duree_seance_min},
          "exercices": [
            {{
              "id": "snake_case_id",
              "nom": "Nom complet de l'exercice",
              "sets": 3,
              "reps": 8,
              "duree_sec": null,
              "repos_sec": 90,
              "conseil": "Conseil technique précis et actionnable en une phrase",
              "media_key": "cle_pour_animation"
            }}
          ]
        }}
      ]
    }}
  ]
}}
```"""


# ─── Parsing JSON robuste ────────────────────────────────────────
def extract_json(raw: str) -> dict:
    """Extrait et parse le JSON même si le modèle ajoute du texte autour."""
    # 1. Cherche un bloc ```json ... ```
    match = re.search(r"```json\s*([\s\S]*?)```", raw)
    if match:
        return json.loads(match.group(1).strip())

    # 2. Cherche un bloc ``` ... ```
    match = re.search(r"```\s*([\s\S]*?)```", raw)
    if match:
        return json.loads(match.group(1).strip())

    # 3. Cherche le premier { ... } complet
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Aucun JSON valide trouvé dans la réponse du modèle")


def validate_programme(data: dict) -> dict:
    """Validation minimale de la structure retournée."""
    required_keys = {"skill_target", "niveau_actuel", "programme"}
    for k in required_keys:
        if k not in data:
            raise ValueError(f"Champ manquant dans la réponse IA : '{k}'")

    if not isinstance(data["programme"], list) or len(data["programme"]) == 0:
        raise ValueError("Le champ 'programme' doit être une liste non vide")

    return data


# ─── Routes ─────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "Calistheni API",
        "version": "1.0.0",
        "status": "running",
        "model": MODEL,
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/generate")
async def generate(data: FormData, request: Request):
    log.info(f"[generate] skill={data.skill_cible} | freq={data.frequence_semaine} | ip={request.client.host}")

    prompt = build_prompt(data)

    try:
        response = mistral.chat.complete(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un coach calisthenics expert. "
                        "Tu réponds TOUJOURS et UNIQUEMENT avec du JSON valide, "
                        "sans aucun texte avant ou après."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2500,
        )
    except Exception as e:
        log.error(f"[generate] Erreur Mistral API : {e}")
        raise HTTPException(status_code=502, detail=f"Erreur API Mistral : {str(e)}")

    raw = response.choices[0].message.content
    log.info(f"[generate] Réponse reçue ({len(raw)} caractères)")

    try:
        parsed = extract_json(raw)
        validated = validate_programme(parsed)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"[generate] Parsing échoué : {e}\nRaw: {raw[:500]}")
        raise HTTPException(
            status_code=422,
            detail=f"La réponse IA n'est pas un JSON valide : {str(e)}",
        )

    log.info(f"[generate] Programme généré : {len(validated.get('programme', []))} semaines")
    return validated


# ─── PDF Generator ──────────────────────────────────────────────
class SendPDFRequest(BaseModel):
    email: str
    programme: dict

def clean(text: str) -> str:
    """Remplace les caractères unicode non supportés par Helvetica."""
    if not text:
        return ""
    replacements = {
        "—": "-", "–": "-", "’": "'", "‘": "'",
        "“": '"', "”": '"', "é": "e", "è": "e",
        "ê": "e", "à": "a", "â": "a", "ô": "o",
        "û": "u", "ù": "u", "î": "i", "ï": "i",
        "ç": "c", "É": "E", "À": "A", "…": "...",
        "°": " deg", "×": "x", "→": "->", "«": '"',
        "»": '"',
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text.encode('latin-1', errors='replace').decode('latin-1')


def generate_pdf(programme: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    skill = clean(programme.get("skill_target", "").upper())
    niveau = clean(programme.get("niveau_actuel", "-"))

    # ── Header ──
    pdf.set_fill_color(20, 20, 20)
    pdf.rect(0, 0, 210, 40, "F")
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 20, "", ln=True)
    pdf.cell(0, 16, f"CALISTHENI - {skill}", ln=True, align="C")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 8, f"Niveau actuel : {niveau}", ln=True, align="C")
    pdf.ln(10)

    # ── Semaines ──
    for week in programme.get("programme", []):
        objectif = clean(week.get("objectif", ""))
        semaine_n = week.get("semaine", "")

        pdf.set_fill_color(232, 99, 42)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 12)
        header_text = f"  SEMAINE {semaine_n}"
        if objectif:
            header_text += f"  -  {objectif}"
        pdf.cell(0, 10, header_text, ln=True, fill=True)
        pdf.ln(3)

        for seance in week.get("seances", []):
            jour = clean(seance.get("jour", "")).upper()
            focus = clean(seance.get("focus", ""))

            pdf.set_fill_color(240, 240, 240)
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("Helvetica", "B", 10)
            jour_text = f"  {jour}"
            if focus:
                jour_text += f"  |  {focus}"
            pdf.cell(0, 8, jour_text, ln=True, fill=True)
            pdf.ln(2)

            for ex in seance.get("exercices", []):
                nom = clean(ex.get("nom", ""))
                conseil = clean(ex.get("conseil", ""))
                sets = ex.get("sets", "")
                reps = ex.get("reps")
                dur = ex.get("duree_sec")
                repos = ex.get("repos_sec", "")
                vol = f"{dur}s hold" if dur else f"{reps} reps"

                pdf.set_text_color(20, 20, 20)
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, f"    {nom}", ln=True)

                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, f"    {sets} series x {vol}  |  Repos : {repos}s", ln=True)

                if conseil:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_text_color(130, 130, 130)
                    pdf.multi_cell(0, 5, f"    -> {conseil}", align="L")
                pdf.ln(2)
            pdf.ln(3)

    # ── Footer ──
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 8, "Genere par calistheni.com - Agent IA Calisthenics", align="C")

    return bytes(pdf.output())


def send_email_with_pdf(to_email: str, programme: dict, pdf_bytes: bytes):
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        raise ValueError("RESEND_API_KEY manquante")

    import urllib.request
    import base64

    skill = programme.get('skill_target', 'Programme')
    pdf_b64 = base64.b64encode(pdf_bytes).decode()

    payload = json.dumps({
        "from": "Calistheni <onboarding@resend.dev>",
        "to": [to_email],
        "subject": f"Ton programme {skill} — Calistheni",
        "html": f"""
        <div style="font-family:sans-serif;max-width:520px;margin:0 auto;background:#0d0d0d;color:#e8eaf0;padding:40px 32px;border-radius:12px;">
          <h1 style="font-size:28px;margin:0 0 8px;color:#fff;">Ton programme est prêt 🔥</h1>
          <p style="color:#999;margin:0 0 24px;">Skill cible : <strong style="color:#e8632a">{skill}</strong></p>
          <p style="color:#ccc;line-height:1.7;">Retrouve ton programme personnalisé de 4 semaines en pièce jointe. Suis la progression et reviens générer un nouveau programme quand tu maîtrises ce skill.</p>
          <p style="margin:32px 0 0;color:#666;font-size:13px;">— Tarik, calistheni.com</p>
        </div>
        """,
        "attachments": [{
            "filename": f"programme_{skill.lower().replace(' ','_')}.pdf",
            "content": pdf_b64
        }]
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            log.info(f"[send_pdf] Email envoyé à {to_email} | id={result.get('id')}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        log.error(f"[send_pdf] Resend error {e.code}: {error_body}")
        raise ValueError(f"Resend {e.code}: {error_body}")


@app.post("/send-pdf")
async def send_pdf(req: SendPDFRequest, request: Request):
    log.info(f"[send_pdf] email={req.email} | skill={req.programme.get('skill_target')}")
    try:
        pdf_bytes = generate_pdf(req.programme)
        send_email_with_pdf(req.email, req.programme, pdf_bytes)
        return {"success": True, "message": f"Programme envoyé à {req.email}"}
    except Exception as e:
        log.error(f"[send_pdf] Erreur : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Gestionnaire d'erreurs global ──────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"[error] Non géré : {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne du serveur", "error": str(exc)},
    )


# ─── Entrypoint (local + Railway) ───────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
