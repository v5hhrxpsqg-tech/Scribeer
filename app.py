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

# Sleutels ophalen uit Render Environment Variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    st.error("⚠️ Systeemfout: API-sleutels ontbreken in Render.")
    st.stop()

# Verbindingen opzetten
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

# CORRECTIE: Gebruik de URL met de 'g'
CALLBACK_URL = "https://v5hhrxpsqg-tech.github.io/Scribeer/callback.html"

if 'final_text' not in st.session_state:
    st.session_state.final_text = None

# =================================================================
# 2. OAUTH CALLBACK AFHANDELING & STATUS
# =================================================================
params = st.query_params

# We richten ons op 'access_token' om de PKCE/Verifier fout te voorkomen
if "access_token" in params:
    try:
        # Sessie direct activeren met het binnengekomen token
        supabase.auth.set_session(params["access_token"], params.get("refresh_token", ""))
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Inlogfout: {e}")

# Check inlogstatus (bepaalt de rest van de UI)
try:
    user_info = supabase.auth.get_user()
    user = user_info.user
    is_logged_in = True if user else False
except Exception:
    user = None
    is_logged_in = False

# =================================================================
# 3. AUDIO VERWERKINGS ENGINE
# =================================================================
def process_audio_logic(audio_file, guest_mode):
    audio_file.seek(0, os.SEEK_END)
    file_mb = audio_file.tell() / (1024 * 1024)
    audio_file.seek(0)
    
    limit_mb = 25 if guest_mode else 100
    if file_mb > limit_mb:
        return "ERROR_TOO_LARGE"

    full_audio = AudioSegment.from_file(audio_file)
    
    if guest_mode and len(full_audio) > 10 * 60 * 1000:
        full_audio = full_audio[:10 * 60 * 1000]

    ten_minutes = 10 * 60 * 1000
    all_transcripts = []
    total_parts = (len(full_audio) // ten_minutes) + 1
    
    p_bar = st.progress(0)
    status_indicator = st.empty()

    for i in range(0, len(full_audio), ten_minutes):
        current_part = (i // ten_minutes) + 1
        status_indicator.text(f"Bezig met verwerken van deel {current_part} van {total_parts}...")
        
        chunk = full_audio[i:i+ten_minutes]
        chunk_name = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_name, format="mp3")
        
        with open(chunk_name, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
            all_transcripts.append(response.text)
        
        os.remove(chunk_name)
        p_bar.progress(current_part / total_parts)
    
    status_indicator.text("✅ Klaar met transcriberen!")
    return " ".join(all_transcripts)

# =================================================================
# 4. DE GEBRUIKERSINTERFACE (UI)
# =================================================================
st.title("Scribeer.nl 🎙️")

st.markdown("""
    **Welkom bij Scribeer!** Met deze AI-tool kan jij je audiobestanden uploaden en automatisch laten transcriberen. 
    De tool herkent zelf of er meerdere sprekers in het audiobestand voorkomen en maakt hier een automatische scheiding in. 
    Dit scheelt jou uren luister- en tikwerk, handig toch!
""")

st.divider()

if not is_logged_in:
    info_col, login_col = st.columns([3, 1])
    with info_col:
        st.info("✨ **Gast-modus:** Gratis preview tot 10 minuten (max 25MB).")
    with login_col:
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

st.sidebar.header("⚙️ Instellingen")
chosen_lang = st.sidebar.selectbox("Vertaal naar:", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])

# =================================================================
# 5. HET VERWERKINGSPROCES (UPLOADER & AI)
# =================================================================
audio_input = st.file_uploader("Selecteer een bestand (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if audio_input and st.session_state.final_text is None:
    if st.button("🚀 Start Verwerking"):
        raw_output = process_audio_logic(audio_input, not is_logged_in)
        
        if raw_output == "ERROR_TOO_LARGE":
            st.error("⚠️ Bestand te groot voor gast-modus. Log in voor 100MB capaciteit.")
        else:
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
        st.subheader("Voorbeeld van de transcriptie:")
        p_len = int(len(output_text) * 0.3)
        st.write(output_text[:p_len] + "...")
        
        st.markdown(f"""
            <div style="background-color:#fef6f6; padding:25px; border-radius:15px; border:2px solid #ff4b4b; margin-top:20px;">
                <h3 style="color:#ff4b4b; margin-top:0;">🔒 Transcriptie Voltooid!</h3>
                <p>Log in met Google om de volledige tekst te bekijken en direct te downloaden als Word of PDF.</p>
            </div>
        """, unsafe_allow_html=True)
        
        pay_auth = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": CALLBACK_URL}
        })
        st.link_button("👉 Nu inloggen met Google", pay_auth.url)
        
    else:
        st.subheader("Jouw Volledige Transcriptie:")
        st.text_area("", output_text, height=400)
        
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            word_doc = Document(); word_doc.add_paragraph(output_text); word_stream = BytesIO(); word_doc.save(word_stream)
            st.download_button("📥 Download als Word", word_stream.getvalue(), "Scribeer_Transcriptie.docx")
        with dl_col2:
            pdf_gen = FPDF(); pdf_gen.add_page(); pdf_gen.set_font("Arial", size=12)
            pdf_gen.multi_cell(0, 10, txt=output_text.encode('latin-1', 'replace').decode('latin-1'))
            st.download_button("📥 Download als PDF", pdf_gen.output(dest='S'), "Scribeer_Transcriptie.pdf")
            
        if st.button("🗑️ Start een nieuwe sessie"):
            st.session_state.final_text = None
            st.rerun()