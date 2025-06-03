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

model = whisper.load_model("small")

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

        result = model.transcribe(**transcribe_args)

        # Generate SRT file
        srt_content = generate_srt(result["segments"])
        with open(temp_srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_content)

        # Format paths for Windows FFmpeg
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
