import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os
from supabase import create_client, Client

# ---- 1. INITIALISATIE ----
st.set_page_config(page_title="Scribeer.nl", page_icon="🎙️", layout="wide")

# Sleutels ophalen uit Render kluis
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    st.error("❌ Configuratie fout: API-sleutels niet gevonden.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

if 'final_text' not in st.session_state:
    st.session_state.final_text = None

# ---- 2. OAUTH URL GENEREREN EN TONEN ----
def get_google_oauth_url():
    """Genereer Google OAuth URL en return deze"""
    try:
        response = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": "https://scribeer.nl"
            }
        })
        
        # Check wat we krijgen
        if response:
            if hasattr(response, 'url'):
                return response.url, None
            elif hasattr(response, 'provider_token'):
                return response.provider_token, None
            else:
                return None, f"Unexpected response type: {type(response)}"
        return None, "No response from Supabase"
        
    except Exception as e:
        return None, str(e)

# ---- 3. OAUTH CALLBACK AFHANDELING ----
query_params = st.query_params

# Check verschillende OAuth return methodes
if "access_token" in query_params:
    try:
        access_token = query_params["access_token"]
        refresh_token = query_params.get("refresh_token", "")
        
        supabase.auth.set_session(access_token, refresh_token)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Login fout (access_token): {e}")

elif "code" in query_params:
    try:
        code = query_params["code"]
        supabase.auth.exchange_code_for_session({"auth_code": code})
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Login fout (code): {e}")

# ---- 4. AUTHENTICATIE CHECK ----
user = None
ingelogd = False

try:
    session = supabase.auth.get_session()
    if session:
        user_response = supabase.auth.get_user()
        user = user_response.user if user_response else None
        ingelogd = bool(user)
except Exception:
    pass

# ---- 5. ZIJBALK ----
st.sidebar.header("⚙️ Instellingen")
target_lang = st.sidebar.selectbox("Vertaal naar:", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])

if ingelogd:
    st.sidebar.write(f"✅ Ingelogd als: {user.email}")
    if st.sidebar.button("Uitloggen"):
        supabase.auth.sign_out()
        st.session_state.final_text = None
        st.rerun()
else:
    # DEBUG: Laat de OAuth URL zien
    st.sidebar.subheader("🔍 Debug Login")
    oauth_url, error = get_google_oauth_url()
    
    if error:
        st.sidebar.error(f"❌ OAuth Error: {error}")
    elif oauth_url:
        st.sidebar.success("✅ OAuth URL gegenereerd")
        st.sidebar.code(oauth_url[:100] + "...", language=None)
    else:
        st.sidebar.warning("⚠️ Geen OAuth URL ontvangen")

# ---- 6. FUNCTIES ----
def transcribe_large_audio(file, is_guest):
    file.seek(0, os.SEEK_END)
    file_size = file.tell() / (1024 * 1024)
    file.seek(0)
    
    max_size = 25 if is_guest else 100
    if file_size > max_size:
        return "SIZE_ERROR", max_size
    
    with st.spinner("Audio voorbereiden..."):
        audio = AudioSegment.from_file(file)
        if is_guest:
            if len(audio) > 10 * 60 * 1000:
                audio = audio[:10 * 60 * 1000]
        
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
        return " ".join(chunks), None

# ---- 7. HOOFDSCHERM ----
st.title("Scribeer 🎙️")

st.markdown("""
**Welkom bij Scribeer!** Met deze AI-tool kan jij je audiobestanden uploaden en automatisch laten transcriberen.
De tool herkent zelf of er meerdere sprekers in het audiobestand voorkomen en maakt hier een automatische scheiding in.
Dit scheelt jou uren luister- en tikwerk, handig toch!
""")

st.divider()

if not ingelogd:
    col_info, col_login = st.columns([3, 1])
    with col_info:
        st.info("✨ **Gast-modus:** Gratis preview tot 10 minuten (max 25MB).")
    
    with col_login:
        # Genereer OAuth URL
        oauth_url, error = get_google_oauth_url()
        
        if error:
            st.error("⚠️ OAuth configuratie probleem")
            with st.expander("Zie details"):
                st.write(error)
                st.write("**Controleer:**")
                st.write("1. Supabase → Authentication → Providers → Google enabled?")
                st.write("2. Supabase → Authentication → URL Configuration → Redirect URL ingesteld?")
        elif oauth_url:
            # Gebruik markdown link ipv st.link_button (soms werkt dit beter)
            st.markdown(f'<a href="{oauth_url}" target="_self" style="display: inline-block; padding: 0.5rem 1rem; background-color: #FF4B4B; color: white; text-decoration: none; border-radius: 0.5rem; font-weight: 600;">🔐 Log in met Google</a>', unsafe_allow_html=True)
        else:
            st.error("⚠️ Kan OAuth URL niet genereren")

else:
    st.success(f"👋 Welkom! Je kunt nu bestanden tot 100MB volledig verwerken.")

uploaded_file = st.file_uploader("Upload audio (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if uploaded_file:
    if st.session_state.final_text is None:
        file_size = uploaded_file.size / (1024 * 1024)
        
        if not ingelogd and file_size > 25:
            st.error(f"⚠️ Dit bestand ({file_size:.1f}MB) is te groot voor gasten.")
            st.warning("Log in met Google om bestanden tot 100MB te verwerken.")
        else:
            if not ingelogd and file_size > 5:
                st.warning("⏱️ Preview: Je ontvangt als gast een transcriptie van de eerste 10 minuten.")
            
            if st.button("🚀 Start Verwerking"):
                result, error = transcribe_large_audio(uploaded_file, is_guest=not ingelogd)
                
                if result == "SIZE_ERROR":
                    st.error("Bestand te groot.")
                else:
                    with st.spinner("AI optimalisatie..."):
                        prompt = "Verdeel de tekst in duidelijke alinea's en sprekers."
                        if target_lang != "Geen (originele taal)":
                            prompt += f" Vertaal naar het {target_lang}."
                        
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "Je bent een professionele notulist."},
                                {"role": "user", "content": f"{prompt}\n\nTekst: {result}"}
                            ]
                        )
                        st.session_state.final_text = response.choices[0].message.content
                        st.rerun()

if st.session_state.final_text:
    final_text = st.session_state.final_text
    
    if not ingelogd:
        preview_lengte = int(len(final_text) * 0.4)
        st.subheader("Voorbeeld:")
        st.write(final_text[:preview_lengte] + "...")
        
        st.markdown("""
        <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border:2px solid #ff4b4b; margin-top:10px; margin-bottom:10px;">
        <h4 style="color:#ff4b4b; margin:0;">🔒 Transcriptie voltooid!</h4>
        <p>Log in met Google om het volledige resultaat te downloaden.</p>
        </div>
        """, unsafe_allow_html=True)
        
        oauth_url, _ = get_google_oauth_url()
        if oauth_url:
            st.markdown(f'<a href="{oauth_url}" target="_self" style="display: inline-block; padding: 0.5rem 1rem; background-color: #FF4B4B; color: white; text-decoration: none; border-radius: 0.5rem; font-weight: 600;">🔐 Nu inloggen met Google</a>', unsafe_allow_html=True)
    else:
        st.subheader("Volledig Resultaat:")
        st.text_area("Transcriptie:", final_text, height=400)
        
        c1, c2 = st.columns(2)
        with c1:
            doc = Document()
            doc.add_paragraph(final_text)
            b = BytesIO()
            doc.save(b)
            st.download_button("Download Word", b.getvalue(), "transcriptie.docx")
        with c2:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, txt=final_text.encode('latin-1','replace').decode('latin-1'))
            st.download_button("Download PDF", pdf.output(dest='S'), "transcriptie.pdf")
        
        if st.button("🗑️ Nieuw bestand"):
            st.session_state.final_text = None
            st.rerun()