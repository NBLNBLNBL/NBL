import streamlit as st
import subprocess
import os
import io
import tempfile
import zipfile
import requests
import base64

# Inject custom CSS for Avenir Next and minimal UI
st.markdown("""
    <style>
    html, body, [class*="css"]  {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        background: #fafbfc !important;
    }
    .stButton>button {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        font-size: 0.93em !important;
        padding: 0.3em 1.1em !important;
        border-radius: 18px !important;
        background: #f4f6fa !important;
        color: #2a2c32 !important;
        border: 1px solid #e5e8ee !important;
        transition: background .2s;
    }
    .stButton>button:hover {
        background: #e9eef5 !important;
        color: #1c1c1c !important;
    }
    .discreet {
        background: #f4f6fa;
        border-radius: 16px;
        padding: 12px 18px;
        font-size: 1em;
        color: #222;
        display: inline-block;
        margin: 12px 0 0 0;
        border: 1px solid #e5e8ee;
    }
    .mainTitle {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        font-weight: 600;
        font-size: 2.2em;
        margin-bottom: 0.4em;
        margin-top: 0.3em;
        color: #2a2c32;
        letter-spacing: -1px;
    }
    .stSlider label {
        font-weight: 500;
        font-size: 1em;
    }
    .stCheckbox>div {
        font-size: 1em;
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
    }
    /* Hide Streamlit header and footer */
    header, footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Minimal title
st.markdown('<div class="mainTitle">audio files</div>', unsafe_allow_html=True)

# Autorun option
if 'autorun' not in st.session_state:
    st.session_state.autorun = True
autorun = st.checkbox("Autorun (envoi auto après upload)", value=st.session_state.autorun, key="autorun")

# Option suppression silence
if 'silence' not in st.session_state:
    st.session_state.silence = False
silence_remove = st.checkbox("Activez la suppression automatique des silences", value=st.session_state.silence, key="silence")

uploaded_file = st.file_uploader(
    "",
    type=["mp3", "wav", "ogg", "flac", "m4a"],
    label_visibility="collapsed"
)

max_size_mb = st.slider(
    "Taille max d'un segment (Mo)", min_value=5, max_value=50, value=23
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

def detect_silences(audio_path, silence_threshold="-30dB", min_silence="0.5"):
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-af", f"silencedetect=noise={silence_threshold}:d={min_silence}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    lines = result.stderr.decode().splitlines()
    silences = []
    for line in lines:
        if "silence_start" in line:
            silences.append(float(line.strip().split("silence_start: ")[1]))
        if "silence_end" in line:
            silences.append(float(line.strip().split("silence_end: ")[1]))
    return silences

def split_by_size(audio_path, output_format, max_size_mb, use_silence=False):
    duration = get_audio_duration(audio_path)
    if not use_silence:
        # Brut découpe par taille
        chunk_dur = 300  # 5min
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

    # Découpe sur silences
    silences = detect_silences(audio_path)
    points = [0.0] + silences
    files = []
    idx = 1
    output_files = []
    # Ajoute la fin du fichier
    points.append(duration)
    seg_start = points[0]
    for seg_end in points[1:]:
        if seg_end - seg_start < 1.0:
            continue
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{output_format}")
        temp.close()
        cmd = [
            "ffmpeg", "-y", "-i", audio_path, "-ss", str(seg_start), "-to", str(seg_end),
            "-c", "copy", temp.name
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.getsize(temp.name) <= max_size_mb * 1024 * 1024:
            output_files.append(temp.name)
            seg_start = seg_end
        else:
            # Si trop gros, coupe en deux
            mid = (seg_start + seg_end) / 2
            points.insert(points.index(seg_end), mid)
            os.unlink(temp.name)
    return output_files

def zip_segments(segment_files, output_format):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for idx, seg_path in enumerate(segment_files):
            seg_name = f"segment_{idx+1}.{output_format}"
            with open(seg_path, "rb") as f:
                zipf.writestr(seg_name, f.read())
    zip_buffer.seek(0)
    return zip_buffer

def reset_states():
    st.session_state.uploaded_file = None
    st.session_state.segments = None
    st.session_state.zip_buffer = None
    st.session_state.uploaded = False
    st.session_state.send_ok = False
    st.session_state.error_msg = None

# App logic
if "uploaded" not in st.session_state:
    st.session_state.uploaded = False
if "send_ok" not in st.session_state:
    st.session_state.send_ok = False
if "zip_buffer" not in st.session_state:
    st.session_state.zip_buffer = None
if "segments" not in st.session_state:
    st.session_state.segments = None
if "error_msg" not in st.session_state:
    st.session_state.error_msg = None

def process_file():
    suffix = "." + uploaded_file.name.split(".")[-1]
    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_audio.write(uploaded_file.read())
    temp_audio.close()

    output_format = uploaded_file.name.split(".")[-1]
    segments = split_by_size(temp_audio.name, output_format, max_size_mb, use_silence=silence_remove)
    zip_buffer = zip_segments(segments, output_format)

    for seg in segments:
        os.unlink(seg)
    os.unlink(temp_audio.name)
    return zip_buffer

def send_to_webhook(zip_buffer):
    zip_buffer.seek(0)
    b64_zip = base64.b64encode(zip_buffer.read()).decode("utf-8")
    data_json = {
        "filename": "segments.zip",
        "file_b64": b64_zip
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=data_json, timeout=60)
        if resp.status_code == 200:
            return True, None
        else:
            return False, f"Envoi échoué (code {resp.status_code})"
    except Exception as e:
        return False, str(e)

# Autorun or manual logic
if uploaded_file and (autorun or st.session_state.uploaded):
    if not st.session_state.uploaded:
        with st.spinner("Traitement du fichier..."):
            st.session_state.zip_buffer = process_file()
            st.session_state.uploaded = True
    if st.session_state.uploaded and not st.session_state.send_ok:
        with st.spinner("Envoi au webhook..."):
            ok, err = send_to_webhook(st.session_state.zip_buffer)
            if ok:
                st.session_state.send_ok = True
                st.session_state.error_msg = None
            else:
                st.session_state.error_msg = err

    if st.session_state.send_ok:
        st.markdown('<div class="discreet">✅ Audio envoyé au webhook.<br>Vous pouvez <b>télécharger le ZIP</b> ci-dessous.</div>', unsafe_allow_html=True)
        st.download_button(
            "Télécharger le zip",
            data=st.session_state.zip_buffer,
            file_name="segments.zip",
            mime="application/zip",
            key="dl_btn"
        )
        # Reset state après download pour éviter les doubles envois
        if autorun:
            reset_states()
    elif st.session_state.error_msg:
        st.markdown(f'<div class="discreet" style="color:#e44">{st.session_state.error_msg}</div>', unsafe_allow_html=True)

elif uploaded_file and not autorun:
    st.audio(uploaded_file, format="audio/mp3")
    if st.button("Confirmer l'envoi"):
        with st.spinner("Traitement du fichier..."):
            st.session_state.zip_buffer = process_file()
        with st.spinner("Envoi au webhook..."):
            ok, err = send_to_webhook(st.session_state.zip_buffer)
            if ok:
                st.session_state.send_ok = True
                st.session_state.error_msg = None
            else:
                st.session_state.error_msg = err
        if st.session_state.send_ok:
            st.markdown('<div class="discreet">✅ Audio envoyé au webhook.<br>Vous pouvez <b>télécharger le ZIP</b> ci-dessous.</div>', unsafe_allow_html=True)
            st.download_button(
                "Télécharger le zip",
                data=st.session_state.zip_buffer,
                file_name="segments.zip",
                mime="application/zip",
                key="dl_btn2"
            )
            reset_states()
        elif st.session_state.error_msg:
            st.markdown(f'<div class="discreet" style="color:#e44">{st.session_state.error_msg}</div>', unsafe_allow_html=True)
