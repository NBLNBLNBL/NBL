import streamlit as st
import subprocess
import os
import io
import tempfile
import zipfile
import requests
import base64

# --- DESIGN MINIMALISTE & AVENIR NEXT ---
st.markdown("""
    <style>
    html, body, [class*="css"]  {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        background: #fafbfc !important;
        letter-spacing: 0.03em;
    }
    .mainTitle {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        font-weight: 700;
        font-size: 2.0em;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        margin-bottom: 0.3em;
        margin-top: 0.1em;
        color: #222;
        text-align: left;
    }
    .desc {
        font-size: 1.04em;
        color: #444;
        margin-bottom: 1.2em;
        margin-top: 0.3em;
    }
    .segmentInfo {
        background: #f6f8fa;
        border-radius: 14px;
        padding: 12px 20px;
        font-size: 1.08em;
        color: #222;
        border: 1px solid #e5e8ee;
        margin-bottom: 1em;
        margin-top: 1em;
        display: inline-block;
        font-weight: 400;
        letter-spacing: 0.01em;
    }
    .confirmBtn {
        font-size: 1.11em !important;
        font-weight: 700 !important;
        padding: 0.25em 1.5em !important;
        border-radius: 22px !important;
        background: #f7f8fa !important;
        color: #222 !important;
        border: 1.7px solid #e5e8ee !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em;
        margin-bottom: 0.5em;
    }
    .confirmBtn:hover {
        background: #e9eef5 !important;
        color: #111 !important;
    }
    .dlBtn {
        font-size: 0.93em !important;
        padding: 0.1em 1.0em !important;
        border-radius: 16px !important;
        background: #f6f7fa !important;
        color: #333 !important;
        border: 1px solid #e5e8ee !important;
        margin-top: 0.5em;
    }
    .discreet {
        background: #f4f6fa;
        border-radius: 14px;
        padding: 11px 16px;
        font-size: 1em;
        color: #222;
        border: 1px solid #e5e8ee;
        display: inline-block;
        margin: 10px 0 0 0;
        font-weight: 400;
    }
    .stSlider label, .stCheckbox>div, .stFileUploader label {
        font-family: 'Avenir Next', 'Avenir', 'Helvetica Neue', Arial, sans-serif;
        font-size: 1.04em;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #222;
    }
    header, footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="mainTitle">audio files</div>', unsafe_allow_html=True)
st.markdown('<div class="desc">Découpez vos fichiers audio automatiquement par taille ou sur les silences.</div>', unsafe_allow_html=True)

# --- PARAMÉTRAGE ---
if 'autorun' not in st.session_state:
    st.session_state.autorun = True
autorun = st.checkbox("Autorun (envoi automatique après upload)", value=st.session_state.autorun, key="autorun")

if 'silence' not in st.session_state:
    st.session_state.silence = False
silence_remove = st.checkbox("SUPPRESSION AUTOMATIQUE DES SILENCES", value=st.session_state.silence, key="silence")

uploaded_file = st.file_uploader(
    "Importer un fichier audio",
    type=["mp3", "wav", "ogg", "flac", "m4a"],
    label_visibility="collapsed"
)

max_size_mb = st.slider(
    "TAILLE MAX PAR SEGMENT (Mo)", min_value=5, max_value=50, value=23
)

WEBHOOK_URL = "https://leroux.app.n8n.cloud/webhook/76480c7e-8f8f-4c9a-a7f8-10db31568227"

# --- UTILITAIRES AUDIO ---
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
        chunk_dur = 300  # 5min
        files = []
        start = 0
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
        return files, duration

    silences = detect_silences(audio_path)
    points = [0.0] + silences
    output_files = []
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
            mid = (seg_start + seg_end) / 2
            points.insert(points.index(seg_end), mid)
            os.unlink(temp.name)
    return output_files, duration

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
    st.session_state.uploaded = False
    st.session_state.send_ok = False
    st.session_state.zip_buffer = None
    st.session_state.segments = None
    st.session_state.segment_info = None
    st.session_state.error_msg = None

def process_file():
    suffix = "." + uploaded_file.name.split(".")[-1]
    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_audio.write(uploaded_file.read())
    temp_audio.close()

    output_format = uploaded_file.name.split(".")[-1]
    segments, duration = split_by_size(temp_audio.name, output_format, max_size_mb, use_silence=silence_remove)
    zip_buffer = zip_segments(segments, output_format)
    for seg in segments:
        os.unlink(seg)
    os.unlink(temp_audio.name)
    return zip_buffer, len(segments), duration

def send_to_webhook(zip_buffer):
    zip_buffer.seek(0)
    b64_zip = base64.b64encode(zip_buffer.read()).decode("utf-8")
    data_json = {
        "filename": "segments.zip",
        "file_b64": b64_zip
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=data_json, timeout=120)
        if resp.status_code == 200:
            return True, None
        else:
            return False, f"Envoi échoué (code {resp.status_code})"
    except Exception as e:
        return False, str(e)

# --- LOGIQUE APP ---
if "uploaded" not in st.session_state:
    st.session_state.uploaded = False
if "send_ok" not in st.session_state:
    st.session_state.send_ok = False
if "zip_buffer" not in st.session_state:
    st.session_state.zip_buffer = None
if "segments" not in st.session_state:
    st.session_state.segments = None
if "segment_info" not in st.session_state:
    st.session_state.segment_info = None
if "error_msg" not in st.session_state:
    st.session_state.error_msg = None

if uploaded_file and not st.session_state.uploaded:
    with st.spinner("Chargement et analyse du fichier… (le temps d’upload dépend de votre connexion)"):
        zip_buffer, seg_count, duration = process_file()
        st.session_state.zip_buffer = zip_buffer
        st.session_state.segments = seg_count
        st.session_state.segment_info = (seg_count, duration)
        st.session_state.uploaded = True

if st.session_state.uploaded and not st.session_state.send_ok:
    seg_count, duration = st.session_state.segment_info if st.session_state.segment_info else (0, 0)
    st.markdown(
        f'<div class="segmentInfo">'
        f'Durée audio détectée : <b>{duration:.1f}s</b> &nbsp;&nbsp;|&nbsp;&nbsp;'
        f'Segments générés : <b>{seg_count}</b> &nbsp;&nbsp;|&nbsp;&nbsp;'
        f'Découpage : <b>{"silences" if silence_remove else "taille brute"}</b>'
        f'</div>', unsafe_allow_html=True
    )
    if autorun:
        with st.spinner("Envoi au webhook…"):
            ok, err = send_to_webhook(st.session_state.zip_buffer)
            if ok:
                st.session_state.send_ok = True
                st.session_state.error_msg = None
            else:
                st.session_state.error_msg = err
    else:
        if st.button("RUN", key="runbtn", help="Lancer l'envoi au webhook", type="primary"):
            with st.spinner("Envoi au webhook…"):
                ok, err = send_to_webhook(st.session_state.zip_buffer)
                if ok:
                    st.session_state.send_ok = True
                    st.session_state.error_msg = None
                else:
                    st.session_state.error_msg = err

if st.session_state.send_ok:
    st.markdown('<div class="discreet">✅ Audio envoyé au webhook.<br>Téléchargez le ZIP ci-dessous.</div>', unsafe_allow_html=True)
    st.download_button(
        "télécharger le zip",
        data=st.session_state.zip_buffer,
        file_name="segments.zip",
        mime="application/zip",
        key="dl_btn"
    )
    reset_states()
elif st.session_state.error_msg:
    st.markdown(f'<div class="discreet" style="color:#e44">{st.session_state.error_msg}</div>', unsafe_allow_html=True)

# UX message supplémentaire
if uploaded_file is None:
    st.markdown(
        '<div class="discreet">L’upload d’un fichier volumineux peut prendre du temps selon votre connexion. L’analyse démarre une fois l’upload terminé.</div>',
        unsafe_allow_html=True
    )
