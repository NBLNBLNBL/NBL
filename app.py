import streamlit as st
from pydub import AudioSegment, silence
import zipfile
import io
import requests
import tempfile
import os

st.set_page_config(page_title="Découpeur Audio Intelligent", page_icon="🎵", layout="centered")

st.title("🎵 Découpeur Audio Intelligent")
st.write("Déposez un fichier audio, segmentez-le automatiquement (≤ 23 Mo par segment, respect du silence), et obtenez un ZIP prêt à envoyer.")

uploaded_file = st.file_uploader(
    "Glissez-déposez un fichier audio ici (mp3, wav, etc.)",
    type=["mp3", "wav", "ogg", "flac", "m4a"]
)

max_size_mb = st.slider(
    "Taille maximale d'un segment (Mo)",
    min_value=5, max_value=50, value=23
)

WEBHOOK_URL = "https://leroux.app.n8n.cloud/webhook/76480c7e-8f8f-4c9a-a7f8-10db31568227"

def get_audio_format(filename):
    ext = filename.lower().split('.')[-1]
    if ext in ["mp3", "wav", "ogg", "flac", "m4a"]:
        return ext
    return "mp3"

def split_audio_on_silence(audio, max_bytes, silence_thresh=-40, min_silence_len=500):
    """
    Découpe l'audio selon les silences détectés, en segments qui ne dépassent pas max_bytes.
    Ne coupe jamais en plein mot.
    """
    chunks = []
    current_chunk = AudioSegment.empty()
    for part in silence.split_on_silence(
        audio, 
        min_silence_len=min_silence_len, 
        silence_thresh=silence_thresh,
        keep_silence=200
    ):
        if len(current_chunk) == 0:
            current_chunk += part
        elif len(current_chunk.raw_data) + len(part.raw_data) <= max_bytes:
            current_chunk += part
        else:
            chunks.append(current_chunk)
            current_chunk = part
    if len(current_chunk) > 0:
        chunks.append(current_chunk)
    return chunks

if uploaded_file:
    st.audio(uploaded_file, format="audio/mp3")
    with st.spinner("Traitement du fichier..."):
        # Sauvegarde temporaire
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix="." + get_audio_format(uploaded_file.name))
        temp_audio.write(uploaded_file.read())
        temp_audio.close()
        file_size = os.path.getsize(temp_audio.name)
        audio_format = get_audio_format(uploaded_file.name)
        audio = AudioSegment.from_file(temp_audio.name, format=audio_format)

        # Analyse rapide du niveau de silence
        sample = audio[:10000] if len(audio) > 10000 else audio
        silence_thresh = sample.dBFS - 10

        max_bytes = max_size_mb * 1024 * 1024
        segments = split_audio_on_silence(audio, max_bytes, silence_thresh=silence_thresh)

        # Création du ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, seg in enumerate(segments):
                seg_io = io.BytesIO()
                seg.export(seg_io, format=audio_format)
                seg_name = f"segment {idx+1}.{audio_format}"
                zipf.writestr(seg_name, seg_io.getvalue())
        zip_buffer.seek(0)

        # Affichage du résultat
        st.success(f"{len(segments)} segments générés.")
        st.download_button(
            "Télécharger le ZIP",
            data=zip_buffer,
            file_name="segments.zip",
            mime="application/zip"
        )

        # Envoi au webhook
        with st.spinner("Envoi au webhook..."):
            zip_buffer.seek(0)
            files = {'file': ('segments.zip', zip_buffer, 'application/zip')}
            try:
                resp = requests.post(WEBHOOK_URL, files=files, timeout=60)
                if resp.status_code == 200:
                    st.success("ZIP envoyé avec succès au webhook !")
                else:
                    st.warning(f"Envoi au webhook échoué (code {resp.status_code})")
            except Exception as e:
                st.warning(f"Erreur lors de l'envoi au webhook: {e}")

        os.unlink(temp_audio.name)
