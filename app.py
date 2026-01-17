import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os
import time
from supabase import create_client, Client

# =================================================================
# 1. INITIALISATIE
# =================================================================
st.set_page_config(
    page_title="Scribeer.nl - Jouw AI Notulist",
    page_icon="🎙️",
    layout="wide"
)

# Sleutels ophalen
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    st.error("⚠️ Systeemfout: API-sleutels ontbreken.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

if 'final_text' not in st.session_state:
    st.session_state.final_text = None
if 'magic_link_sent' not in st.session_state:
    st.session_state.magic_link_sent = False

# =================================================================
# 2. EMAIL MAGIC LINK AUTH
# =================================================================
params = st.query_params

# Debug: toon URL params als er wat is
if params:
    with st.sidebar.expander("🔍 URL Debug", expanded=False):
        st.write("URL parameters ontvangen:")
        st.write(dict(params))

# Check voor error in URL
if "error" in params:
    error_msg = params.get("error_description", params.get("error", "Onbekende fout"))
    st.error(f"❌ Login fout: {error_msg}")
    st.query_params.clear()

# Check voor tokens in URL (van magic link callback)
if "access_token" in params:
    access_token = params["access_token"]
    refresh_token = params.get("refresh_token", "")

    try:
        user_response = supabase.auth.get_user(access_token)

        if user_response and user_response.user:
            st.session_state.user = user_response.user
            st.session_state.authenticated = True
            st.session_state.access_token = access_token
            st.query_params.clear()
            st.success("✅ Succesvol ingelogd!")
            st.rerun()
        else:
            st.error("❌ Login mislukt. Probeer opnieuw.")
            st.query_params.clear()
            st.rerun()

    except Exception as e:
        st.error(f"❌ Login fout: {str(e)}")
        st.query_params.clear()
        st.rerun()

# Check authenticatie status
user = None
is_logged_in = False

if st.session_state.get('authenticated') and st.session_state.get('user'):
    user = st.session_state.user
    is_logged_in = True

# =================================================================
# 3. AUDIO VERWERKING
# =================================================================
def transcribe_chunk_with_retry(chunk_path, max_retries=3):
    """Transcribeert een audio chunk met retry logica."""
    for attempt in range(max_retries):
        try:
            with open(chunk_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )
                return response.text
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                continue
            else:
                raise e
    return None

def process_audio_logic(audio_file, guest_mode):
    """Verwerkt audio, hakt in stukken en stuurt naar Whisper."""
    audio_file.seek(0, os.SEEK_END)
    file_mb = audio_file.tell() / (1024 * 1024)
    audio_file.seek(0)

    limit_mb = 25 if guest_mode else 200
    if file_mb > limit_mb:
        return "ERROR_TOO_LARGE"

    # Initialiseer progress tracking in session_state
    if 'transcription_progress' not in st.session_state:
        st.session_state.transcription_progress = []

    # Sla bestand eerst lokaal op voor stabielere verwerking
    temp_input_file = f"temp_input_{int(time.time())}.audio"
    try:
        with st.spinner("Audio uploaden..."):
            with open(temp_input_file, "wb") as f:
                f.write(audio_file.read())

        with st.spinner("Audio laden en decoderen..."):
            full_audio = AudioSegment.from_file(temp_input_file)

        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)

    except Exception as e:
        if os.path.exists(temp_input_file):
            os.remove(temp_input_file)
        st.error(f"❌ Kon audio niet laden: {str(e)}")
        return "ERROR_LOAD_FAILED"

    if guest_mode and len(full_audio) > 10 * 60 * 1000:
        full_audio = full_audio[:10 * 60 * 1000]

    ten_minutes = 10 * 60 * 1000
    total_parts = (len(full_audio) // ten_minutes) + 1

    # Bereken geschatte tijd
    audio_duration_min = len(full_audio) / 60000
    st.info(f"📊 Audio duur: {audio_duration_min:.1f} minuten ({total_parts} {'deel' if total_parts == 1 else 'delen'})")

    p_bar = st.progress(0)
    status_container = st.empty()
    error_container = st.empty()

    all_transcripts = st.session_state.transcription_progress.copy()
    start_index = len(all_transcripts) * ten_minutes

    for i in range(start_index, len(full_audio), ten_minutes):
        current_part = (i // ten_minutes) + 1

        with status_container.container():
            st.write(f"🎧 **Deel {current_part} van {total_parts}** wordt verwerkt...")
            st.caption("Dit kan even duren. Sluit dit venster niet.")

        chunk = full_audio[i:i+ten_minutes]
        chunk_name = f"temp_chunk_{i}.mp3"

        try:
            chunk.export(chunk_name, format="mp3")

            transcript = transcribe_chunk_with_retry(chunk_name)

            if transcript:
                all_transcripts.append(transcript)
                st.session_state.transcription_progress = all_transcripts.copy()

            if os.path.exists(chunk_name):
                os.remove(chunk_name)

        except Exception as e:
            if os.path.exists(chunk_name):
                os.remove(chunk_name)

            error_container.error(f"❌ Fout bij deel {current_part}: {str(e)}")

            if all_transcripts:
                st.warning(f"⚠️ {len(all_transcripts)} van {total_parts} delen zijn wel verwerkt.")
                st.session_state.transcription_progress = []
                return " ".join(all_transcripts)
            else:
                st.session_state.transcription_progress = []
                return "ERROR_TRANSCRIPTION_FAILED"

        p_bar.progress(current_part / total_parts)

    p_bar.empty()
    status_container.empty()
    st.session_state.transcription_progress = []

    return " ".join(all_transcripts)

# =================================================================
# 4. SIDEBAR
# =================================================================
st.sidebar.header("⚙️ Instellingen")

# DEBUG INFO
with st.sidebar.expander("🔧 Debug Info"):
    st.write(f"**Ingelogd:** {is_logged_in}")
    if user:
        st.write(f"**Email:** {user.email}")
        st.write(f"**User ID:** {user.id}")
    try:
        session_check = supabase.auth.get_session()
        st.write(f"**Sessie actief:** {'Ja' if session_check else 'Nee'}")
    except:
        st.write("**Sessie actief:** Nee")

if is_logged_in:
    st.sidebar.success(f"✅ Ingelogd als: {user.email}")
    if st.sidebar.button("Uitloggen"):
        # Verwijder session state
        if 'authenticated' in st.session_state:
            del st.session_state.authenticated
        if 'user' in st.session_state:
            del st.session_state.user
        if 'access_token' in st.session_state:
            del st.session_state.access_token
        if 'refresh_token' in st.session_state:
            del st.session_state.refresh_token

        st.session_state.final_text = None
        st.session_state.magic_link_sent = False
        st.rerun()
else:
    st.sidebar.info("Je bent niet ingelogd")

chosen_lang = st.sidebar.selectbox(
    "Vertaal naar:", 
    ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"]
)

# =================================================================
# 5. HOOFDSCHERM
# =================================================================
st.title("Scribeer 🎙️")

st.markdown("""
**Welkom bij Scribeer!** Met deze AI-tool kan jij je audiobestanden uploaden en automatisch laten transcriberen. 
De tool herkent zelf of er meerdere sprekers in het audiobestand voorkomen en maakt hier een automatische scheiding in. 
Dit scheelt jou uren luister- en tikwerk, handig toch!
""")

st.divider()

# =================================================================
# 6. LOGIN SECTIE (EMAIL MAGIC LINK)
# =================================================================
if not is_logged_in:
    info_col, login_col = st.columns([2, 1])
    
    with info_col:
        st.info("✨ **Gast-modus:** Gratis preview tot 10 minuten (max 25MB).")
    
    with login_col:
        if not st.session_state.magic_link_sent:
            with st.form("email_login"):
                email = st.text_input("📧 Email adres", placeholder="jouw@email.nl")
                submit = st.form_submit_button("🔐 Log in")
                
                if submit and email:
                    try:
                        # Stuur magic link naar email
                        supabase.auth.sign_in_with_otp({
                            "email": email,
                            "options": {
                                "email_redirect_to": "https://v5hhrxpsqg-tech.github.io/Scribeer/callback.html"
                            }
                        })
                        st.session_state.magic_link_sent = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fout: {e}")
        else:
            st.success("📧 Check je email!")
            st.caption("Klik op de link in je email om in te loggen.")
            if st.button("Andere email gebruiken"):
                st.session_state.magic_link_sent = False
                st.rerun()
else:
    st.success(f"👋 Welkom! Je kunt nu bestanden tot 200MB volledig verwerken.")

# =================================================================
# 7. BESTAND UPLOADEN & VERWERKEN
# =================================================================
audio_input = st.file_uploader("Upload audio (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if audio_input and st.session_state.final_text is None:
    file_mb = audio_input.size / (1024 * 1024)
    
    if not is_logged_in and file_mb > 25:
        st.error(f"⚠️ Dit bestand ({file_mb:.1f}MB) is te groot voor gasten.")
        st.warning("Log in om bestanden tot 200MB te verwerken.")
    else:
        if not is_logged_in and file_mb > 5:
            st.warning("⏱️ Preview: Je ontvangt als gast een transcriptie van de eerste 10 minuten.")
        
        if st.button("🚀 Start Verwerking"):
            raw_output = process_audio_logic(audio_input, not is_logged_in)

            if raw_output == "ERROR_TOO_LARGE":
                st.error("⚠️ Bestand te groot.")
            elif raw_output == "ERROR_LOAD_FAILED":
                st.error("⚠️ Kon het audiobestand niet laden. Probeer een ander formaat.")
            elif raw_output == "ERROR_TRANSCRIPTION_FAILED":
                st.error("⚠️ Transcriptie mislukt. Probeer het later opnieuw.")
            else:
                with st.spinner("🤖 AI analyseert sprekers en deelt tekst in..."):
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
# 8. RESULTAAT & DOWNLOADS
# =================================================================
if st.session_state.final_text:
    output_text = st.session_state.final_text
    
    if not is_logged_in:
        st.subheader("Voorbeeld:")
        preview_len = int(len(output_text) * 0.4)
        st.write(output_text[:preview_len] + "...")
        
        st.markdown("""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border:2px solid #ff4b4b; margin-top:10px;">
                <h4 style="color:#ff4b4b; margin:0;">🔒 Transcriptie voltooid!</h4>
                <p>Log in om het volledige resultaat te downloaden.</p>
            </div>
        """, unsafe_allow_html=True)
        
        st.info("👆 Vul je email in bovenaan om in te loggen")
        
    else:
        st.subheader("Volledig Resultaat:")
        st.text_area("Transcriptie:", output_text, height=400)
        
        col1, col2 = st.columns(2)
        with col1:
            word_doc = Document()
            word_doc.add_paragraph(output_text)
            word_stream = BytesIO()
            word_doc.save(word_stream)
            st.download_button("📥 Download Word", word_stream.getvalue(), "transcriptie.docx")
            
        with col2:
            pdf_gen = FPDF()
            pdf_gen.add_page()
            pdf_gen.set_font("Arial", size=12)
            safe_text = output_text.encode('latin-1', 'replace').decode('latin-1')
            pdf_gen.multi_cell(0, 10, txt=safe_text)
            st.download_button("📥 Download PDF", pdf_gen.output(dest='S'), "transcriptie.pdf")
            
        if st.button("🗑️ Nieuw bestand"):
            st.session_state.final_text = None
            st.rerun()