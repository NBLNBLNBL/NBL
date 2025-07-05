import streamlit as st
import subprocess
import os
import io
import tempfile
import zipfile
import requests

st.set_page_config(page_title="Découpeur Audio Intelligent", page_icon="🎵", layout="centered")

st.title("🎵 Découpeur Audio Intelligent")
st.write("Déposez un fichier audio, segmentez-le automatiquement (≤ 23 Mo par segment), et obtenez un ZIP prêt à envoyer au webhook.")

uploaded_file = st.file_uploader(
    "Glissez-déposez un fichier audio ici (mp3, wav, etc.)",
    type=["mp3", "wav", "ogg", "flac", "m4a"]
)

max_size_mb = st.slider(
    "Taille maximale d'un segment (Mo)",
    min_value=5, max_value=50, value=23
)

WEBHOOK_URL = "https://leroux.app.n8n.cloud/webhook/76480c7e-8f8f-4c9a-a7f8-10db31568227"

def get_audio_duration(audio_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    return float(result.stdout.decode().strip())

def split_by_size(audio_path, output_format, max_size_mb):
    duration = get_audio_duration(audio_path)
    chunk_dur = 300  # 5min par défaut
    files = []
    start = 0
    idx = 1
    while start < duration:
        end = min(start + chunk_dur, duration)
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{output_format}")
        temp.close()
        cmd = [
            "ffmpeg", "-y", "-i", audio_path, "-ss", str(start), "-to", str(end),
            "-c", "copy", temp.name
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.getsize(temp.name) > max_size_mb * 1024 * 1024:
            chunk_dur = chunk_dur // 2
            os.unlink(temp.name)
            continue
        files.append(temp.name)
        start = end
        idx += 1
    return files

def zip_segments(segment_files, output_format):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for idx, seg_path in enumerate(segment_files):
            seg_name = f"segment {idx+1}.{output_format}"
            with open(seg_path, "rb") as f:
                zipf.writestr(seg_name, f.read())
    zip_buffer.seek(0)
    return zip_buffer

if uploaded_file:
    st.audio(uploaded_file, format="audio/mp3")
    with st.spinner("Traitement du fichier..."):
        suffix = "." + uploaded_file.name.split(".")[-1]
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_audio.write(uploaded_file.read())
        temp_audio.close()

        output_format = uploaded_file.name.split(".")[-1]
        segment_files = split_by_size(temp_audio.name, output_format, max_size_mb)
        zip_buffer = zip_segments(segment_files, output_format)

        st.success(f"{len(segment_files)} segments générés.")
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
        for seg in segment_files:
            os.unlink(seg)
