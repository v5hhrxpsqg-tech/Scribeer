import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os
from supabase import create_client, Client

# --- 1. INITIALISATIE & CONFIGURATIE ---
st.set_page_config(page_title="Scribeer.nl", page_icon="🎙️", layout="wide")

# Haal sleutels op uit de Render kluis
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Stop de app als de sleutels missen (veiligheidscheck)
if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    st.error("❌ Configuratie fout: API-sleutels niet gevonden in Render Environment Variables.")
    st.stop()

# Verbindingen maken
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

# Geheugen instellen (Session State)
if 'final_text' not in st.session_state:
    st.session_state.final_text = None

# --- 2. AUTHENTICATIE CHECK (De Fix) ---
try:
    # We proberen de huidige gebruiker op te halen
    user_response = supabase.auth.get_user()
    user = user_response.user
    ingelogd = True if user else False
except Exception:
    # Als er een fout is (bijv. geen sessie), dan is er niemand ingelogd
    user = None
    ingelogd = False

# --- 3. ZIJBALK ---
st.sidebar.header("⚙️ Instellingen")
target_lang = st.sidebar.selectbox("Vertaal naar:", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])

if ingelogd:
    st.sidebar.write(f"✅ Ingelogd als: {user.email}")
    if st.sidebar.button("Uitloggen"):
        supabase.auth.sign_out()
        st.session_state.final_text = None # Wis tekst bij uitloggen voor privacy
        st.rerun()

# --- 4. FUNCTIES ---
def transcribe_large_audio(file, is_guest):
    # Check bestandsgrootte
    file.seek(0, os.SEEK_END)
    file_size = file.tell() / (1024 * 1024) 
    file.seek(0)

    # Grenzen: 25MB voor gasten, 100MB voor leden (dankzij je Standard pakket!)
    max_size = 25 if is_guest else 100 
    if file_size > max_size:
        st.error(f"⚠️ Bestand te groot (max {max_size}MB).")
        st.stop()

    with st.spinner("Audio voorbereiden..."):
        audio = AudioSegment.from_file(file)
        if is_guest:
            # Gasten krijgen altijd maar de eerste 10 minuten
            if len(audio) > 10 * 60 * 1000:
                audio = audio[:10 * 60 * 1000]
                st.warning("⏱️ Preview modus: Alleen de eerste 10 minuten worden verwerkt.")

    # Splitsen in stukjes van 10 min voor Whisper (OpenAI limiet)
    chunk_length = 10 * 60 * 1000 
    chunks = []
    
    for i in range(0, len(audio), chunk_length):
        chunk = audio[i:i+chunk_length]
        chunk_path = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_path, format="mp3")
        
        with open(chunk_path, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
            chunks.append(response.text)
        os.remove(chunk_path)
        
    return " ".join(chunks)

# --- 5. HOOFDSCHERM ---
st.title("Scribeer.nl 🎙️")

if not ingelogd:
    st.info("✨ **Probeer het gratis:** Upload een fragment tot 10 minuten voor een preview.")
else:
    st.success(f"🔓 Welkom terug! Je kunt nu volledige bestanden tot 100MB uploaden.")

uploaded_file = st.file_uploader("Upload audio (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if uploaded_file:
    # Alleen verwerken als we nog geen tekst in het geheugen hebben
    if st.session_state.final_text is None:
        if st.button("🚀 Start Verwerking"):
            try:
                full_text = transcribe_large_audio(uploaded_file, is_guest=not ingelogd)
                
                with st.spinner("AI optimalisatie en opmaak..."):
                    prompt = "Verdeel de tekst in duidelijke alinea's en sprekers."
                    if target_lang != "Geen (originele taal)":
                        prompt += f" Vertaal de tekst volledig naar het {target_lang}."
                    
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Je bent een professionele notulist."},
                            {"role": "user", "content": f"{prompt}\n\nTekst: {full_text}"}
                        ]
                    )
                    st.session_state.final_text = response.choices[0].message.content
                    st.rerun()
            except Exception as e:
                st.error(f"Er ging iets mis bij de verwerking: {e}")

    # Als er tekst is, toon de resultaten of de paywall
    if st.session_state.final_text:
        final_text = st.session_state.final_text
        
        if not ingelogd:
            # PAYWALL MODUS
            preview_lengte = int(len(final_text) * 0.4)
            st.subheader("Voorbeeld van je transcriptie:")
            st.write(final_text[:preview_lengte] + "...")
            
            st.markdown("""
                <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border:2px solid #ff4b4b; margin-top:20px; margin-bottom:20px;">
                    <h3 style="color:#ff4b4b; margin-top:0;">🔒 De volledige transcriptie is klaar!</h3>
                    <p>Log in met je Google account om het volledige resultaat te bekijken en te downloaden als Word of PDF.</p>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("👉 Log in met Google voor volledig resultaat"):
                # Supabase Google Login aanroepen
                auth_response = supabase.auth.sign_in_with_oauth({
                    "provider": "google",
                    "options": {
                        "redirect_to": "https://scribeer.nl"
                    }
                })
                # Gebruiker doorsturen naar Google
                if auth_response.url:
                    st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{auth_response.url}\'">', unsafe_allow_html=True)
        
        else:
            # VOLLEDIGE MODUS (Ingelogd)
            st.subheader("Volledig Resultaat:")
            st.text_area("Transcriptie:", final_text, height=400)
            
            col1, col2 = st.columns(2)
            with col1:
                doc = Document()
                doc.add_paragraph(final_text)
                bio = BytesIO()
                doc.save(bio)
                st.download_button("Download als Word", bio.getvalue(), "transcriptie.docx")
            with col2:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, txt=final_text.encode('latin-1', 'replace').decode('latin-1'))
                st.download_button("Download als PDF", pdf.output(dest='S'), "transcriptie.pdf")
            
            if st.button("🗑️ Wis tekst en upload nieuw bestand"):
                st.session_state.final_text = None
                st.rerun()