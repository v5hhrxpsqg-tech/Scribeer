import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os

# --- 1. CONFIGURATIE & STATUS ---
st.set_page_config(page_title="Scribeer.nl", page_icon="🎙️", layout="wide")

if 'ingelogd' not in st.session_state:
    st.session_state.ingelogd = False

# --- 2. ZIJBALK INSTELLINGEN ---
st.sidebar.header("⚙️ Instellingen")
target_lang = st.sidebar.selectbox("Vertaal naar (optioneel):", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])
output_format = st.sidebar.radio("Standaard download formaat:", ["Word (.docx)", "PDF (.pdf)", "Tekst (.txt)"])

if st.session_state.ingelogd:
    if st.sidebar.button("Uitloggen"):
        st.session_state.ingelogd = False
        st.rerun()

client = OpenAI(api_key="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")

# --- 3. DE VERBETERDE VEILIGE FUNCTIE (VERVANGT DE OUDE) ---
def transcribe_large_audio(file, is_guest):
    # Check bestandsgrootte voordat we RAM belasten
    file.seek(0, os.SEEK_END)
    file_size = file.tell() / (1024 * 1024) 
    file.seek(0)

    # Blokkeer te grote bestanden voor gasten (voorkomt Render crash)
    if is_guest and file_size > 25:
        st.error("⚠️ Dit bestand is te groot voor de gratis versie (max 25MB).")
        st.info("Maak een account aan om grotere bestanden te verwerken.")
        st.stop()

    with st.spinner("Audio voorbereiden en inkorten..."):
        audio = AudioSegment.from_file(file)
        # Voor gasten: Snijd fysiek af bij 10 min (bespaart OpenAI kosten)
        if is_guest:
            ten_minutes = 10 * 60 * 1000
            if len(audio) > ten_minutes:
                audio = audio[:ten_minutes]
                st.warning("⏱️ Alleen de eerste 10 minuten worden verwerkt als gast.")

    # Splitsen voor Whisper
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

# --- 4. HOOFDSCHERM ---
st.title("Scribeer.nl 🎙️")

if not st.session_state.ingelogd:
    st.info("✨ **Probeer het gratis:** Upload een fragment tot 10 minuten voor een directe preview.")
else:
    st.success("🔓 Je bent ingelogd als Pro gebruiker.")

uploaded_file = st.file_uploader("Upload audio (MP3, WAV, M4A)", type=["mp3", "wav", "m4a"])

if uploaded_file:
    if st.button("Start Verwerking"):
        with st.spinner("Bezig met verwerken..."):
            try:
                # Roep de veilige functie aan
                full_text = transcribe_large_audio(uploaded_file, is_guest=not st.session_state.ingelogd)
            except Exception as e:
                st.error(f"Fout bij verwerking: {e}")
                st.stop()

            # AI Optimalisatie
            with st.spinner("AI optimalisatie en vertaling..."):
                prompt = "Verdeel de tekst in duidelijke alinea's en sprekers. "
                if target_lang != "Geen (originele taal)":
                    prompt += f"Vertaal de gehele tekst naar het {target_lang}."
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Je bent een professionele notulist."},
                        {"role": "user", "content": f"{prompt}\n\nTekst: {full_text}"}
                    ]
                )
                final_text = response.choices[0].message.content

            st.success("Verwerking voltooid!")

            # --- 5. PAYWALL LOGICA ---
            if not st.session_state.ingelogd:
                # Gast ziet maar 40%
                preview_lengte = int(len(final_text) * 0.4)
                st.subheader("Voorbeeld van je transcriptie")
                st.write(final_text[:preview_lengte] + "...")
                
                st.markdown("""
                    <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border:2px solid #ff4b4b; margin-top:20px;">
                        <h3 style="color:#ff4b4b; margin-top:0;">🔒 De volledige transcriptie is klaar!</h3>
                        <p>Maak een gratis account aan om het volledige resultaat te zien en te kunnen downloaden.</p>
                    </div>
                """, unsafe_allow_html=True)
                
                if st.button("👉 Maak een gratis account"):
                    st.session_state.ingelogd = True
                    st.rerun()
            else:
                st.subheader("Resultaat:")
                st.text_area("Volledige transcriptie:", final_text, height=400)
                
                # Download knoppen
                col1, col2 = st.columns(2)
                with col1:
                    doc = Document()
                    doc.add_paragraph(final_text)
                    bio = BytesIO()
                    doc.save(bio)
                    st.download_button("Download Word", bio.getvalue(), "transcript.docx")
                with col2:
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", size=12)
                    pdf.multi_cell(0, 10, txt=final_text.encode('latin-1', 'replace').decode('latin-1'))
                    st.download_button("Download PDF", pdf.output(dest='S'), "transcript.pdf")