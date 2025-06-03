from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import whisper
import tempfile
import os
import subprocess
import uuid

app = Flask(__name__)
CORS(app)

# Optional: set max file upload size to 100MB
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

model = None

def get_model():
    global model
    if model is None:
        model = whisper.load_model("small")
    return model

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:06.3f}".replace('.', ',')

def generate_srt(segments):
    srt = ""
    for i, segment in enumerate(segments, start=1):
        start = format_timestamp(segment['start'])
        end = format_timestamp(segment['end'])
        text = segment['text'].strip().replace('-->', '→')  # Avoid breaking SRT format
        srt += f"{i}\n{start} --> {end}\n{text}\n\n"
    return srt

@app.route('/transcribe', methods=['POST'])
def transcribe():
    file = request.files['file']
    language = request.form.get('language')

    # Sanitize filename
    safe_filename = secure_filename(file.filename)
    unique_id = uuid.uuid4().hex
    temp_input_path = os.path.join(tempfile.gettempdir(), f"{unique_id}_{safe_filename}")
    file.save(temp_input_path)

    # Check if FFmpeg is available
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return jsonify({"error": "FFmpeg is not available on the server."}), 500

    # Prepare paths
    temp_srt_path = temp_input_path + ".srt"
    output_video_path = temp_input_path + "_subtitled.mp4"

    try:
        # Transcribe with Whisper
        transcribe_args = {
            "audio": temp_input_path,
            "task": "transcribe",
            "verbose": False
        }
        if language:
            transcribe_args["language"] = language

        result = get_model().transcribe(**transcribe_args)

        # Generate SRT file
        srt_content = generate_srt(result["segments"])
        with open(temp_srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_content)

        # Format paths for FFmpeg
        ffmpeg_input = temp_input_path.replace('\\', '/')
        ffmpeg_output = output_video_path.replace('\\', '/')
        ffmpeg_srt = temp_srt_path.replace('\\', '/').replace(":", "\\:").replace("'", "\\'")

        # Burn subtitles into video using FFmpeg
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i", ffmpeg_input,
            "-vf", f"subtitles='{ffmpeg_srt}'",
            "-c:a", "copy",
            ffmpeg_output
        ]
        subprocess.run(ffmpeg_cmd, check=True)

    except subprocess.CalledProcessError as e:
        return jsonify({"error": "Failed to generate subtitled video", "details": str(e)}), 500
    finally:
        # Clean up input + srt, but keep output
        if os.path.exists(temp_input_path):
            os.remove(temp_input_path)
        if os.path.exists(temp_srt_path):
            os.remove(temp_srt_path)

    return jsonify({
        "text": result["text"],
        "language": result.get("language"),
        "video_filename": os.path.basename(output_video_path)
    })

@app.route('/download-video/<filename>', methods=['GET'])
def download_video(filename):
    path = os.path.join(tempfile.gettempdir(), filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "Video not found", 404
