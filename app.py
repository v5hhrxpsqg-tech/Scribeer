import streamlit as st
from openai import OpenAI
from docx import Document
from fpdf import FPDF
from io import BytesIO
from pydub import AudioSegment
import os

st.set_page_config(page_title="Scribeer.nl", page_icon="🎙️", layout="wide")

# --- ZIJBALK INSTELLINGEN ---
st.sidebar.header("⚙️ Instellingen")
target_lang = st.sidebar.selectbox("Vertaal naar (optioneel):", ["Geen (originele taal)", "Nederlands", "Engels", "Duits", "Frans", "Spaans"])
output_format = st.sidebar.radio("Standaard download formaat:", ["Word (.docx)", "PDF (.pdf)", "Tekst (.txt)"])

client = OpenAI(api_key="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")

# --- FUNCTIE VOOR AUDIO SPLITSEN ---
def transcribe_large_audio(file):
    audio = AudioSegment.from_file(file)
    ten_minutes = 10 * 60 * 1000 # Whisper limiet veiligheid
    chunks = []
    
    # Als bestand groter is dan 25MB (geschat op basis van tijd)
    for i in range(0, len(audio), ten_minutes):
        chunk = audio[i:i+ten_minutes]
        chunk_path = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_path, format="mp3")
        
        with open(chunk_path, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f)
            chunks.append(response.text)
        os.remove(chunk_path)
    return " ".join(chunks)

# --- HOOFDSCHERM ---
st.title("Scribeer")
uploaded_file = st.file_uploader("Upload audio", type=["mp3", "wav", "m4a"])

if uploaded_file:
    if st.button("Start Verwerking"):
        with st.spinner("Bezig met verwerken (ook grote bestanden)..."):
            # 1. Transcriberen (met split-logica)
            try:
                full_text = transcribe_large_audio(uploaded_file)
            except Exception as e:
                st.error(f"Fout bij transcriptie: {e}")
                st.stop()

            # 2. AI Bewerking (Sprekers + Vertaling)
            with st.spinner("AI optimalisatie en vertaling..."):
                prompt = f"Verdeel de tekst in sprekers. "
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

            st.success("Klaar!")
            st.text_area("Resultaat:", final_text, height=300)

            # --- EXPORT LOGICA ---
            if output_format == "Word (.docx)":
                doc = Document()
                doc.add_paragraph(final_text)
                bio = BytesIO()
                doc.save(bio)
                st.download_button("Download Word", bio.getvalue(), "transcript.docx")
            
            elif output_format == "PDF (.pdf)":
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", size=12)
                pdf.multi_cell(0, 10, txt=final_text.encode('latin-1', 'replace').decode('latin-1'))
                st.download_button("Download PDF", pdf.output(dest='S'), "transcript.pdf")
            
            else:
                st.download_button("Download Tekst", final_text, "transcript.txt")