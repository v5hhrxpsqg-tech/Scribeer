import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os
from supabase import create_client, Client

# =================================================================
# 1. INITIALISATIE & BEVEILIGING
# =================================================================
st.set_page_config(
    page_title="Scribeer.nl - Jouw AI Notulist",
    page_icon="🎙️",
    layout="wide"
)

# Sleutels ophalen uit de Render Environment Variables
# NOOIT je sleutels hier letterlijk typen (i.v.m. je publieke GitHub)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Check of alles aanwezig is
if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    st.error("⚠️ Systeemfout: API-sleutels ontbreken in Render. Controleer je Environment Variables.")
    st.stop()

# Verbindingen opzetten
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

# Jouw GitHub Pages URL voor de Google Redirect
CALLBACK_URL = "https://v5hhrxpsqg-tech.github.io/Scribeer/callback.html"

# Zorg dat de tekst bewaard blijft als de pagina ververst
if 'final_text' not in st.session_state:
    st.session_state.final_text = None

# =================================================================
# 2. GOOGLE OAUTH CALLBACK HANDLING
# =================================================================
# Wanneer je terugkomt van de GitHub-tussenpagina, staan er tokens in de URL.
# Dit blokje vangt die tokens op en logt je echt in bij Supabase.
query_params = st.query_params

if "access_token" in query_params:
    access_token = query_params["access_token"]
    refresh_token = query_params.get("refresh_token", "")
    
    # Sessie herstellen bij Supabase
    supabase.auth.set_session(access_token, refresh_token)
    
    # URL opschonen voor een nette look
    st.query_params.clear()
    st.rerun()

# Controleren of we nu een actieve gebruiker hebben
try:
    current_user_res = supabase.auth.get_user()
    user = current_user_res.user
    is_logged_in = True if user else False
except Exception:
    user = None
    is_logged_in = False

# =================================================================
# 3. AUDIO VERWERKINGS ENGINE
# =================================================================
def process_audio_logic(audio_file, guest_mode):
    """
    Deze functie doet het zware werk:
    - Checkt de bestandsgrootte
    - Hakt audio in stukken van 10 min (Whisper limiet)
    - Toont een voortgangsbalk
    - Stuurt alles naar OpenAI
    """
    # 1. Bestandsgrootte checken
    audio_file.seek(0, os.SEEK_END)
    file_mb = audio_file.tell() / (1024 * 1024)
    audio_file.seek(0)
    
    # Limiet bepalen
    limit_mb = 25 if guest_mode else 100
    if file_mb > limit_mb:
        return "ERROR_TOO_LARGE"

    # 2. Audio inladen
    full_audio = AudioSegment.from_file(audio_file)
    
    # 3. Gasten afkappen op 10 minuten
    if guest_mode and len(full_audio) > 10 * 60 * 1000:
        full_audio = full_audio[:10 * 60 * 1000]

    # 4. Chunking (Splitsen in delen)
    ten_minutes = 10 * 60 * 1000
    all_transcripts = []
    total_parts = (len(full_audio) // ten_minutes) + 1
    
    # UI Elementen voor voortgang
    p_bar = st.progress(0)
    status_indicator = st.empty()

    for i in range(0, len(full_audio), ten_minutes):
        current_part = (i // ten_minutes) + 1
        status_indicator.text(f"Bezig met verwerken van deel {current_part} van {total_parts}...")
        
        # Stukje audio exporteren naar tijdelijk bestand
        chunk = full_audio[i:i+ten_minutes]
        chunk_name = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_name, format="mp3")
        
        # Naar OpenAI sturen
        with open(chunk_name, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1", 
                file=f
            )
            all_transcripts.append(response.text)
        
        # Opruimen
        os.remove(chunk_name)
        p_bar.progress(current_part / total_parts)
    
    status_indicator.text("✅ Klaar met transcriberen!")
    return " ".join(all_transcripts)

# =================================================================
# 4. DE GEBRUIKERSINTERFACE (UI)
# =================================================================
st.title("Scribeer.nl 🎙️")

# Welkomsttekst (zoals gevraagd)
st.markdown("""
    **Welkom bij Scribeer!** Met deze AI-tool kan jij je audiobestanden uploaden en automatisch laten transcriberen. 
    De tool herkent zelf of er meerdere sprekers in het audiobestand voorkomen en maakt hier een automatische scheiding in. 
    Dit scheelt jou uren luister- en tikwerk, handig toch!
""")

st.divider()

# Authenticatie status & Inlogknop
if not is_logged_in:
    info_col, login_col = st.columns([3, 1])
    with info_col:
        st.info("✨ **Gast-modus:** Gratis preview tot 10 minuten (max 25MB).")
    with login_col:
        # De slimme Google-link via jouw GitHub-tussenstop
        google_auth = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": CALLBACK_URL}
        })
        st.link_button("🔑 Log in met Google", google_auth.url)
else:
    st.success(f"🔓 Ingelogd als: **{user.email}**")
    if st.sidebar.button("Uitloggen"):
        supabase.auth.sign_out()
        st.session_state.final_text = None
        st.rerun()

# Zijbalk instellingen
st.sidebar.header("⚙️ Instellingen")
chosen_lang = st.sidebar.selectbox(
    "Vertaal naar:", 
    ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"]
)

# =================================================================
# 5. HET VERWERKINGSPROCES (UPLOADER & AI)
# =================================================================
audio_input = st.file_uploader("Selecteer een bestand (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if audio_input and st.session_state.final_text is None:
    if st.button("🚀 Start Verwerking"):
        # Stap A: Transcriberen
        raw_output = process_audio_logic(audio_input, not is_logged_in)
        
        if raw_output == "ERROR_TOO_LARGE":
            st.error("⚠️ Bestand te groot voor gast-modus. Log in voor 100MB capaciteit.")
        else:
            # Stap B: AI Opschonen (Alinea's en spreker-labels)
            with st.spinner("De AI analyseert nu de sprekers en deelt de tekst in..."):
                instr = "Verdeel de tekst in duidelijke alinea's en geef sprekers aan (bijv. Spreker 1, Spreker 2)."
                if chosen_lang != "Geen (originele taal)":
                    instr += f" Vertaal de gehele tekst naar het {chosen_lang}."
                
                ai_res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Je bent een professionele en nauwkeurige notulist."},
                        {"role": "user", "content": f"{instr}\n\nTekst: {raw_output}"}
                    ]
                )
                st.session_state.final_text = ai_res.choices[0].message.content
                st.rerun()

# =================================================================
# 6. RESULTAAT, PAYWALL & DOWNLOADS
# =================================================================
if st.session_state.final_text:
    output_text = st.session_state.final_text
    
    if not is_logged_in:
        # PAYWALL VOOR GASTEN
        st.subheader("Voorbeeld van de transcriptie:")
        p_len = int(len(output_text) * 0.3)
        st.write(output_text[:p_len] + "...")
        
        st.markdown(f"""
            <div style="background-color:#fef6f6; padding:25px; border-radius:15px; border:2px solid #ff4b4b; margin-top:20px;">
                <h3 style="color:#ff4b4b; margin-top:0;">🔒 Transcriptie Voltooid!</h3>
                <p>Log in met Google om de volledige tekst te bekijken en direct te downloaden als Word of PDF.</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Nogmaals de inlogknop voor het gemak
        pay_auth = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": CALLBACK_URL}
        })
        st.link_button("👉 Nu inloggen met Google", pay_auth.url)
        
    else:
        # VOLLEDIG RESULTAAT VOOR LEDEN
        st.subheader("Jouw Volledige Transcriptie:")
        st.text_area("", output_text, height=400)
        
        # Download knoppen naast elkaar
        dl_col1, dl_col2 = st.columns(2)
        
        with dl_col1:
            # Word export
            word_doc = Document()
            word_doc.add_paragraph(output_text)
            word_stream = BytesIO()
            word_doc.save(word_stream)
            st.download_button("📥 Download als Word", word_stream.getvalue(), "Scribeer_Transcriptie.docx")
            
        with dl_col2:
            # PDF export (met fix voor speciale tekens)
            pdf_gen = FPDF()
            pdf_gen.add_page()
            pdf_gen.set_font("Arial", size=12)
            safe_text = output_text.encode('latin-1', 'replace').decode('latin-1')
            pdf_gen.multi_cell(0, 10, txt=safe_text)
            st.download_button("📥 Download als PDF", pdf_gen.output(dest='S'), "Scribeer_Transcriptie.pdf")
            
        if st.button("🗑️ Start een nieuwe sessie"):
            st.session_state.final_text = None
            st.rerun()