import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os
from supabase import create_client, Client

# --- 1. INITIALISATIE ---
st.set_page_config(page_title="Scribeer.nl", page_icon="🎙️", layout="wide")

# Haal sleutels op uit de Render kluis
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Verbind met Supabase & OpenAI
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

# Geheugen instellen
if 'final_text' not in st.session_state:
    st.session_state.final_text = None

# --- 2. AUTHENTICATIE CHECK ---
# We kijken of de gebruiker al is ingelogd via Supabase
user = supabase.auth.get_user()
ingelogd = True if user.user else False

# --- 3. ZIJBALK ---
st.sidebar.header("⚙️ Instellingen")
target_lang = st.sidebar.selectbox("Vertaal naar:", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])

if ingelogd:
    st.sidebar.write(f"✅ Ingelogd als: {user.user.email}")
    if st.sidebar.button("Uitloggen"):
        supabase.auth.sign_out()
        st.session_state.final_text = None
        st.rerun()

# --- 4. FUNCTIES ---
def transcribe_large_audio(file, is_guest):
    file.seek(0, os.SEEK_END)
    file_size = file.tell() / (1024 * 1024) 
    file.seek(0)

    # Omdat je nu een Standard pakket hebt, verhogen we de grens voor ingelogden!
    max_size = 25 if is_guest else 100 
    if file_size > max_size:
        st.error(f"⚠️ Bestand te groot (max {max_size}MB).")
        st.stop()

    with st.spinner("Audio voorbereiden..."):
        audio = AudioSegment.from_file(file)
        if is_guest:
            # Gasten krijgen nog steeds maar 10 min
            audio = audio[:10 * 60 * 1000]
            st.warning("⏱️ Preview modus: Alleen de eerste 10 minuten worden verwerkt.")

    # Verdelen in stukjes van 10 min voor Whisper
    chunk_length = 10 * 60 * 1000 
    chunks = []
    for i in range(0, len(audio), chunk_length):
        chunk = audio[i:i+chunk_length]
        chunk_path = f"temp_{i}.mp3"
        chunk.export(chunk_path, format="mp3")
        with open(chunk_path, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
            chunks.append(response.text)
        os.remove(chunk_path)
    return " ".join(chunks)

# --- 5. HOOFDSCHERM ---
st.title("Scribeer.nl 🎙️")

if not ingelogd:
    st.info("✨ **Probeer het gratis:** Upload tot 10 minuten voor een preview.")
else:
    st.success("🔓 Welkom terug! Je kunt nu volledige bestanden uploaden.")

uploaded_file = st.file_uploader("Upload audio (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if uploaded_file:
    if st.session_state.final_text is None:
        if st.button("🚀 Start Verwerking"):
            full_text = transcribe_large_audio(uploaded_file, is_guest=not ingelogd)
            
            with st.spinner("AI optimalisatie..."):
                prompt = "Verdeel de tekst in duidelijke alinea's en sprekers."
                if target_lang != "Geen (originele taal)":
                    prompt += f" Vertaal naar het {target_lang}."
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Je bent een professionele notulist."},
                        {"role": "user", "content": f"{prompt}\n\nTekst: {full_text}"}
                    ]
                )
                st.session_state.final_text = response.choices[0].message.content
                st.rerun()

    if st.session_state.final_text:
        final_text = st.session_state.final_text
        
        if not ingelogd:
            # PAYWALL
            preview_lengte = int(len(final_text) * 0.4)
            st.subheader("Voorbeeld:")
            st.write(final_text[:preview_lengte] + "...")
            
            st.markdown('<div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border:2px solid #ff4b4b;">🔒 <b>Volledige transcriptie klaar!</b></div>', unsafe_allow_html=True)
            
            if st.button("👉 Log in met Google om alles te zien"):
                # DIT IS DE ECHTE GOOGLE INLOG
                auth_url = supabase.auth.sign_in_with_oauth({
                    "provider": "google",
                    "options": {"redirect_to": "https://scribeer.nl"}
                })
                st.markdown(f'<meta http-equiv="refresh" content="0;URL=\'{auth_url.url}\'">', unsafe_allow_html=True)
        else:
            # VOLLEDIGE RESULTAAT
            st.subheader("Resultaat:")
            st.text_area("Tekst:", final_text, height=400)
            
            col1, col2 = st.columns(2)
            with col1:
                doc = Document(); doc.add_paragraph(final_text); b = BytesIO(); doc.save(b)
                st.download_button("Download Word", b.getvalue(), "transcript.docx")
            with col2:
                pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", size=12); pdf.multi_cell(0, 10, txt=final_text.encode('latin-1','replace').decode('latin-1'))
                st.download_button("Download PDF", pdf.output(dest='S'), "transcript.pdf")
            
            if st.button("🗑️ Nieuw bestand"):
                st.session_state.final_text = None
                st.rerun()